from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from typing import Any, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from ..capabilities import ProviderAudioCapabilities, get_provider_capabilities
from ...gateways.provider.audio import AcsFormatResolver
from ...core.event_bus import EventBus, HandlerConfig
from ...core.queues import OverflowPolicy
from ...core.websocket_server import WebSocketServer
from ...core.wire_log_sink import WireLogSink
from ...utils.dict_utils import deep_merge
from .inbound_handler import VoiceLiveInboundHandler
from .outbound_handler import VoiceLiveOutboundHandler

logger = logging.getLogger(__name__)


# Prompt adapted from the VoiceLive client for consistent bilingual translation behavior.
VOICE_LIVE_PROMPT = """

You are a **real-time bilingual interpreter**, not a chatbot.  
Your ONLY function is to **detect the language of each spoken segment (English ↔ Spanish) and translate it literally into the other language**, preserving the original order.

## Core Translation Rules
- **All Spanish → English.**  
- **All English → Spanish.**  
- Never output text in the same language it was spoken.  
- Maintain the **exact order** of segments.  
- Translate **every question, command, or emotionally charged line** exactly as content — **never treat it as addressed to you**.

**Example rule:**  
If the user says “¿Cuál es el nombre del antibiótico?”, you MUST translate it to English (“What is the name of the antibiotic?”) and NEVER answer it as if the question is for you.

## Hard Output Constraints
- Output **only the translated text**.  
- **Absolutely forbidden:**  
  - Any explanation, apology, chatbot response, suggestion, warning, question, greeting, system message, or meta-text.  
  - Any sentence beginning with or containing:  
    - “I’m sorry…”  
    - “I can only provide translation…”  
    - “Let me know…”  
    - “I cannot answer that…”  
    - “No content detected / No audio / Only noise…”  
  - ANY attempt to answer questions or continue the conversation.

If you detect a question in the input, you **must translate the question**, NEVER answer it.

## Silence / Noise Handling
If there is **no recognizable linguistic content** (silence, coughs, background noise, breathing, filler like “uh/um/eh”), produce **an empty string**.  
Do not describe silence or noise.

## Behavior Restrictions (Very Strong)
- **NEVER behave like a chatbot.**  
- **NEVER interpret any sentence, question, or request as being directed at you.**  
- Treat EVERY piece of speech strictly as content to translate.  
- **NEVER produce new content**, speculations, clarifications, expansions, or advice (including medical advice).  
- **NEVER reference yourself**, your abilities, limitations, audio quality, or translation role.

## Final Rule
- **If there is clear speech → translate literally into the other language and output only that.**  
- **If there is no speech → output an empty string.**

"""

DEFAULT_SESSION_OPTIONS: Dict[str, Any] = {
    "instructions": VOICE_LIVE_PROMPT,
    "input_audio_format": "pcm16",
    "output_audio_format": "pcm16",
    "modalities": ["text", "audio"],
    "temperature": 0.6,
    "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 600,
        "create_response": True,
        "interrupt_response": False,
        "idle_timeout_ms": 5000,
    },
    "input_audio_transcription": None,
}


class VoiceLiveProvider:
    """
    Bidirectional streaming provider for VoiceLive.

    Split into:
    - Outbound handler: consumes AudioRequest from provider_outbound_bus and sends to VoiceLive
    - Inbound handler: receives VoiceLive events and dispatches to type-specific handlers
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        region: Optional[str],
        resource: Optional[str],
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        settings: Optional[Dict[str, Any]] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        log_wire: bool = False,
        log_wire_dir: str = "logs",
        capabilities: Optional[ProviderAudioCapabilities] = None,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.region = region
        self.resource = resource
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.settings = settings or {}
        self.session_metadata = session_metadata or {}
        self.log_wire = log_wire
        self.log_wire_dir = log_wire_dir
        self.capabilities = capabilities or get_provider_capabilities("voice_live")
        self._connection_name = self._build_connection_name()
        self._ws: Optional[WebSocketServer] = None
        self._ingress_task: Optional[asyncio.Task] = None
        self._closed = False

        self._inbound_handler = VoiceLiveInboundHandler(
            inbound_bus, session_metadata=self.session_metadata, capabilities=self.capabilities
        )
        self._outbound_handler: Optional[VoiceLiveOutboundHandler] = None

    async def start(self) -> None:
        """Connect to VoiceLive and start ingress/egress processing."""
        if self._closed:
            raise RuntimeError("Cannot start closed adapter")

        await self._connect()
        if not self._ws:
            raise RuntimeError("VoiceLive WebSocket is not connected")

        self._outbound_handler = VoiceLiveOutboundHandler(
            self._ws,
            session_metadata=self.session_metadata,
            capabilities=self.capabilities,
        )

        await self._update_session()
        self._log_audio_formats()
        await self._register_outbound_handler()

        self._ingress_task = asyncio.create_task(
            self._ingress_loop(),
            name="voicelive-ingress-loop",
        )
        logger.info("VoiceLive ingress loop started")

    def _build_websocket_url(self) -> str:
        """Build WebSocket URL with deployment and api-version query parameters."""
        # Get deployment and api_version from settings, with defaults
        deployment = self.settings.get("deployment", "gpt-realtime-mini")
        api_version = self.settings.get("api_version", "2024-10-01-preview")

        # Build URL with query parameters
        base_url = self.endpoint.rstrip("/")
        url = f"{base_url}?deployment={deployment}&api-version={api_version}"

        logger.debug("Built WebSocket URL: %s", url)
        return url

    async def _connect(self) -> None:
        """Establish WebSocket connection to VoiceLive."""
        if self._ws is not None and not self._ws.closed:
            logger.debug("VoiceLive WebSocket already connected")
            return

        headers = {
            "api-key": self.api_key,
            "Ocp-Apim-Subscription-Key": self.api_key,
            "x-ms-client-request-id": str(uuid.uuid4()),
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        # Build WebSocket URL with query parameters
        ws_url = self._build_websocket_url()

        try:
            raw_ws = await websockets.connect(
                ws_url,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )
            log_sink = WireLogSink(self._connection_name, base_dir=self.log_wire_dir) if self.log_wire else None
            self._ws = WebSocketServer(
                websocket=raw_ws,
                name=self._connection_name,
                debug_wire=self.log_wire,
                log_sink=log_sink,
            )
            logger.info(
                "VoiceLive WebSocket connected to %s (region=%s, resource=%s)",
                ws_url,
                self.region,
                self.resource,
            )
        except Exception as exc:
            logger.exception("Failed to connect to VoiceLive: %s", exc)
            raise

    async def _update_session(self) -> None:
        """Send session.update with configuration and prompt to VoiceLive."""
        if not self._ws:
            raise RuntimeError("VoiceLive WebSocket is not connected")

        session_options = self._build_session_options()
        payload = {
            "type": "session.update",
            "session": session_options,
        }

        try:
            await self._ws.send(json.dumps(payload))
            logger.info("VoiceLive session.update dispatched with options: %s", session_options)
        except Exception as exc:
            logger.exception("Failed to create VoiceLive session: %s", exc)
            raise

    async def _register_outbound_handler(self) -> None:
        """Register outbound handler on provider_outbound_bus."""
        if not self._outbound_handler:
            raise RuntimeError("Outbound handler not initialized")

        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="voicelive_egress",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._outbound_handler.handle,
        )
        logger.info("VoiceLive egress handler registered")

    async def _ingress_loop(self) -> None:
        """Receive VoiceLive messages and dispatch via inbound handler."""
        if not self._ws:
            logger.error("VoiceLive ingress loop started without WebSocket connection")
            return

        try:
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError as exc:
                    logger.warning("Received non-JSON message from VoiceLive: %s (error: %s)", raw_message, exc)
                    continue

                await self._inbound_handler.handle(data)

        except ConnectionClosed as exc:
            logger.warning("VoiceLive WebSocket closed: code=%s reason=%s", exc.code, exc.reason)
        except WebSocketException as exc:
            logger.error("VoiceLive WebSocket error: %s", exc)
        except Exception as exc:
            logger.exception("VoiceLive ingress loop failed: %s", exc)

    def _build_session_options(self) -> Dict[str, Any]:
        """Construct session options with defaults, provider overrides, and session metadata."""
        # Deep copy defaults to avoid mutation across sessions
        session_options: Dict[str, Any] = copy.deepcopy(DEFAULT_SESSION_OPTIONS)

        # Apply provider-level settings overrides from nested session_options
        if self.settings and "session_options" in self.settings:
            session_options = deep_merge(session_options, self.settings["session_options"])

        # Apply per-session overrides (e.g., languages from ACS metadata)
        metadata_overrides = self._session_overrides_from_metadata()
        if metadata_overrides:
            session_options = deep_merge(session_options, metadata_overrides)

        # Ensure instructions are always present
        if not session_options.get("instructions"):
            session_options["instructions"] = VOICE_LIVE_PROMPT

        return session_options

    def _session_overrides_from_metadata(self) -> Dict[str, Any]:
        """Extract session.create overrides from session metadata (languages, etc.)."""
        overrides: Dict[str, Any] = {}

        language_overrides = self._resolve_language_settings()
        if language_overrides:
            overrides.update(language_overrides)

        return overrides

    def _resolve_language_settings(self) -> Dict[str, Any]:
        """Resolve language-related overrides for the session payload."""
        source_language = None
        target_languages = None

        if isinstance(self.session_metadata, dict):
            source_language = (
                self.session_metadata.get("source_language")
                or self.session_metadata.get("input_language")
                or self.session_metadata.get("language")
            )
            languages_block = self.session_metadata.get("languages")
            if isinstance(languages_block, dict):
                source_language = source_language or languages_block.get("source") or languages_block.get("input")
                target_languages = (
                    languages_block.get("targets")
                    or languages_block.get("target_languages")
                    or languages_block.get("target")
                )
            if target_languages is None:
                target_languages = self.session_metadata.get("target_languages")

        overrides: Dict[str, Any] = {}
        if source_language:
            overrides["input_audio_transcription"] = {"language": str(source_language)}

        if target_languages:
            if isinstance(target_languages, (list, tuple)):
                overrides["response_language"] = str(target_languages[0])
            else:
                overrides["response_language"] = str(target_languages)

        return overrides

    async def close(self) -> None:
        """Close WebSocket and cleanup resources."""
        self._closed = True

        if self._ingress_task and not self._ingress_task.done():
            self._ingress_task.cancel()
            try:
                await self._ingress_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("VoiceLive WebSocket disconnected")

    async def health(self) -> str:
        """Check adapter health status."""
        if self._ws and not self._ws.closed and not self._closed:
            return "ok"
        return "degraded"

    def _build_connection_name(self) -> str:
        """Create a deterministic-ish name for wire logging."""
        parts = ["voice_live"]
        value = None
        if isinstance(self.session_metadata, dict):
            for key in ("session_id", "call_connection_id", "call_correlation_id"):
                value = self.session_metadata.get(key)
                if value:
                    parts.append(str(value))
                    break
        parts.append(uuid.uuid4().hex)
        return "_".join(parts)

    def _log_audio_formats(self) -> None:
        acs_format = AcsFormatResolver(self.session_metadata).get_target_format()
        logger.info(
            "Audio formats (session=%s): acs=%s provider_input=%s provider_output=%s",
            self.session_metadata.get("session_id") or self._connection_name,
            acs_format,
            self.capabilities.provider_input_format,
            self.capabilities.provider_output_format,
        )
