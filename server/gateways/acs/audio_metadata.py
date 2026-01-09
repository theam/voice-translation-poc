from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from ...models.gateway_input_event import GatewayInputEvent

logger = logging.getLogger(__name__)


class AudioMetadataHandler:
    """
    Handles ACS AudioMetadata messages (strict to current ACS payload shape).

    Expected ACS payload in envelope.payload:
      {
        "subscriptionId": "...",
        "encoding": "PCM",
        "sampleRate": 16000,
        "channels": 1,
        "length": 640
      }

    Stores a canonical format record in session_metadata for later use
    (e.g., AudioData handling, resampling/adaptation for translation providers).

    After storing metadata, triggers pipeline_completion_callback to signal
    that provider initialization can begin (all configuration messages received).
    """

    SESSION_KEY = "acs_audio"

    def __init__(
        self,
        session_metadata: Dict[str, Any],
        pipeline_completion_callback: Optional[Callable[[], Awaitable[None]]] = None
    ):
        self.session_metadata = session_metadata
        self.pipeline_completion_callback = pipeline_completion_callback

    def can_handle(self, event: GatewayInputEvent) -> bool:
        payload = event.payload or {}
        if not isinstance(payload, dict):
            return False

        return payload.get("kind") == "AudioMetadata"

    async def handle(self, event: GatewayInputEvent) -> None:
        logger.info("Handling AudioMetadata: %s (session=%s)", event.event_id, event.session_id)

        payload = event.payload or {}
        meta = payload.get("audiometadata") or {}

        if not isinstance(meta, dict) or not meta:
            logger.warning(
                "Expected audioMetadata dict payload (event_id=%s)",
                event.event_id,
            )
            return

        # Extract exactly what we need later (no validation here)
        encoding = meta.get("encoding")
        encoding_normalized = str(encoding).lower() if encoding is not None else None
        if encoding_normalized and encoding_normalized.startswith("pcm"):
            encoding_normalized = "pcm16"

        def _to_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        stream_format = {
            "source": "acs",
            "subscription_id": meta.get("subscriptionId"),
            "encoding": encoding_normalized or "pcm16",          # e.g., "pcm16"
            "sample_rate_hz": _to_int(meta.get("sampleRate")),   # e.g., 16000
            "channels": _to_int(meta.get("channels")),           # e.g., 1
            "frame_bytes": _to_int(meta.get("length")),          # bytes per frame (often 20ms)
            # PCM defaults: keep this as a convenient downstream hint
            "bits_per_sample": 16,
        }

        state = self.session_metadata.setdefault(self.SESSION_KEY, {})
        state["format"] = stream_format
        state["audio_ready"] = True
        state["metadata_message_id"] = event.event_id
        state["metadata_received_at_utc"] = event.received_at_utc

        logger.info(
            "Stored ACS audio metadata (session=%s): sub=%s enc=%s sr=%s ch=%s frame_bytes=%s",
            event.session_id,
            stream_format.get("subscription_id"),
            stream_format.get("encoding"),
            stream_format.get("sample_rate_hz"),
            stream_format.get("channels"),
            stream_format.get("frame_bytes"),
        )

        # Trigger provider initialization now that metadata is available
        if self.pipeline_completion_callback:
            logger.info(
                "Triggering provider processing start (session=%s)",
                event.session_id
            )
            await self.pipeline_completion_callback()
