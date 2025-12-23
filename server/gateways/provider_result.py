from __future__ import annotations

import logging
import time
import base64
from collections import defaultdict
from typing import Any, Dict, Optional, Tuple, Union

from ..core.event_bus import EventBus
from ..models.messages import ProviderOutputEvent, TranslationResponse
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class ProviderResultHandler(Handler):
    """
    Handles normalized provider output events.
    Receives ProviderOutputEvent (or legacy TranslationResponse) from provider_inbound_bus and
    publishes ACS-ready payloads (audio frames, stop controls, transcripts) to acs_outbound_bus.
    """

    def __init__(
        self,
        settings: HandlerSettings,
        acs_outbound_bus: EventBus,
        translation_settings: Dict[str, Any],
        session_metadata: Dict[str, Any],
    ):
        super().__init__(settings)
        self.acs_outbound_bus = acs_outbound_bus
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata
        self._audio_buffers: Dict[str, bytearray] = defaultdict(bytearray)
        self._outgoing_seq: Dict[str, int] = defaultdict(int)

    async def handle(self, response: Union[TranslationResponse, ProviderOutputEvent]) -> None:
        logger.info(
            "Provider result received type=%s session=%s participant=%s commit=%s",
            getattr(response, "event_type", None) or getattr(response, "partial", None),
            getattr(response, "session_id", None),
            getattr(response, "participant_id", None),
            getattr(response, "commit_id", None),
        )

        event = self._coerce_event(response)
        if not event:
            logger.warning("Unsupported provider result payload: %s", type(response))
            return

        if event.event_type == "audio.delta":
            await self._handle_audio_delta(event)
        elif event.event_type == "audio.done":
            await self._handle_audio_done(event)
        elif event.event_type == "control":
            await self._handle_control(event)
        elif event.event_type in {"transcript.delta", "transcript.done"}:
            await self._handle_transcript(event)
        else:
            logger.debug("Ignoring unsupported provider output event: %s", event.event_type)

    def _coerce_event(self, response: Union[TranslationResponse, ProviderOutputEvent]) -> Optional[ProviderOutputEvent]:
        if isinstance(response, ProviderOutputEvent):
            return response
        if isinstance(response, TranslationResponse):
            return ProviderOutputEvent(
                commit_id=response.commit_id,
                session_id=response.session_id,
                participant_id=response.participant_id,
                event_type="transcript.done" if not response.partial else "transcript.delta",
                payload={"text": response.text, "final": not response.partial},
                provider="unknown",
                stream_id=response.commit_id,
            )
        return None

    async def _handle_audio_delta(self, event: ProviderOutputEvent) -> None:
        payload = event.payload or {}
        audio_b64 = payload.get("audio_b64")
        if not audio_b64:
            logger.debug("Audio delta missing payload.audio_b64: %s", payload)
            return

        buffer_key = self._buffer_key(event)
        frame_bytes, format_info = self._frame_config(event)

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=False)
        except Exception as exc:
            logger.exception("Failed to decode audio for stream %s: %s", buffer_key, exc)
            await self._publish_audio_done(event, reason="error", error=str(exc))
            return

        self._audio_buffers[buffer_key] += audio_bytes
        seq = payload.get("seq")
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            seq,
            len(audio_bytes),
            len(self._audio_buffers[buffer_key]),
        )

        await self._flush_frames(event, buffer_key, frame_bytes, format_info)

    async def _handle_audio_done(self, event: ProviderOutputEvent) -> None:
        buffer_key = self._buffer_key(event)
        frame_bytes, format_info = self._frame_config(event)
        await self._flush_frames(event, buffer_key, frame_bytes, format_info, drain=True)

        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None
        await self._publish_audio_done(event, reason=reason or "completed", error=error)

        # Clear any leftover buffer/sequence state
        self._audio_buffers.pop(buffer_key, None)
        self._outgoing_seq.pop(buffer_key, None)

    async def _handle_control(self, event: ProviderOutputEvent) -> None:
        payload = event.payload or {}
        action = payload.get("action")
        if action != "stop_audio":
            logger.debug("Control event ignored (action=%s)", action)
            return

        buffer_key = self._buffer_key(event)
        self._audio_buffers.pop(buffer_key, None)
        self._outgoing_seq.pop(buffer_key, None)

        acs_payload = {
            "type": "control.stop_audio",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "detail": payload.get("detail"),
        }
        await self.acs_outbound_bus.publish(acs_payload)
        logger.info("Published stop_audio control for %s", buffer_key)

    async def _handle_transcript(self, event: ProviderOutputEvent) -> None:
        payload = event.payload or {}
        text = payload.get("text")
        if not text:
            logger.debug("Transcript event missing text: %s", payload)
            return

        final_flag = bool(payload.get("final")) if payload.get("final") is not None else event.event_type.endswith("done")
        translation_payload = {
            "type": "translation.result",
            "partial": not final_flag,
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "text": text,
            "final": final_flag,
            "timestamp_ms": event.timestamp_ms or int(time.time() * 1000),
        }
        await self.acs_outbound_bus.publish(translation_payload)

        if self.translation_settings.get("transcript") and not final_flag:
            text_delta_payload = {
                "type": "control.test.response.text_delta",
                "participant_id": event.participant_id or "unknown",
                "delta": text,
                "timestamp_ms": int(time.time() * 1000),
            }
            await self.acs_outbound_bus.publish(text_delta_payload)

    async def _flush_frames(
        self,
        event: ProviderOutputEvent,
        buffer_key: str,
        frame_bytes: int,
        format_info: Dict[str, Any],
        drain: bool = False,
    ) -> None:
        buffer = self._audio_buffers.get(buffer_key, bytearray())

        while len(buffer) >= frame_bytes or (drain and buffer):
            frame = bytes(buffer[:frame_bytes])
            del buffer[:frame_bytes]
            outgoing_seq = self._next_outgoing_seq(buffer_key)

            acs_payload = {
                "type": "audio.out",
                "session_id": event.session_id,
                "participant_id": event.participant_id,
                "commit_id": event.commit_id,
                "stream_id": event.stream_id,
                "provider": event.provider,
                "seq": outgoing_seq,
                "format": format_info,
                "audio_b64": base64.b64encode(frame).decode("ascii"),
            }
            await self.acs_outbound_bus.publish(acs_payload)

        self._audio_buffers[buffer_key] = buffer

    def _frame_config(self, event: ProviderOutputEvent) -> Tuple[int, Dict[str, Any]]:
        format_info = {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1}
        payload_format = event.payload.get("format") if isinstance(event.payload, dict) else None
        if isinstance(payload_format, dict):
            format_info.update({k: v for k, v in payload_format.items() if v is not None})

        metadata_format = (
            self.session_metadata.get("acs_audio", {}).get("format")
            if isinstance(self.session_metadata, dict)
            else None
        )
        frame_bytes = 0
        if isinstance(metadata_format, dict):
            frame_bytes = int(metadata_format.get("frame_bytes") or 0)
            for key in ("encoding", "sample_rate_hz", "channels"):
                if metadata_format.get(key):
                    format_info[key] = metadata_format[key]

        if frame_bytes <= 0:
            sample_rate = int(format_info.get("sample_rate_hz") or 16000)
            channels = int(format_info.get("channels") or 1)
            frame_bytes = int((sample_rate / 1000) * 20 * channels * 2)

        return frame_bytes, format_info

    def _buffer_key(self, event: ProviderOutputEvent) -> str:
        participant = event.participant_id or "unknown"
        stream = event.stream_id or event.commit_id or "stream"
        return f"{event.session_id}:{participant}:{stream}"

    def _next_outgoing_seq(self, buffer_key: str) -> int:
        self._outgoing_seq[buffer_key] = self._outgoing_seq.get(buffer_key, 0) + 1
        return self._outgoing_seq[buffer_key]

    async def _publish_audio_done(self, event: ProviderOutputEvent, *, reason: str, error: Optional[str]) -> None:
        payload = {
            "type": "audio.done",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "reason": reason,
            "error": error,
        }
        await self.acs_outbound_bus.publish(payload)
