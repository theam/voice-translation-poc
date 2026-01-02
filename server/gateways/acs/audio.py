from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import numpy as np

from ...config import BatchingConfig
from ...audio import Base64AudioCodec, PcmConverter
from ...models.gateway_input_event import GatewayInputEvent
from ...core.event_bus import EventBus
from ...models.provider_events import ProviderInputEvent
from ...services.audio_duration import AudioDurationCalculator

logger = logging.getLogger(__name__)


AudioKey = Tuple[str, str | None]


@dataclass
class ParticipantState:
    """Tracks batching state for a single participant."""
    accumulated_bytes: int = 0  # Raw PCM byte count
    accumulated_duration_ms: float = 0.0  # Audio duration in milliseconds
    last_message_time: float = 0.0  # Monotonic time of last audio chunk
    idle_timer_task: Optional[asyncio.Task] = None  # Async task for idle timeout
    # Lightweight audio activity tracking (for barge-in detection)
    last_activity_time: float = 0.0
    is_active: bool = False
    last_rms: float = 0.0


@dataclass
class AudioActivityEvent:
    """Lightweight activity signal emitted from inbound ACS audio."""

    session_id: str
    participant_id: Optional[str]
    rms: float
    peak: int
    timestamp_monotonic: float
    received_at_utc: str
    frame_bytes: int


class AudioMessageHandler:
    """Consumes audio envelopes, buffers audio, and dispatches to provider."""

    def __init__(
        self,
        provider_outbound_bus: EventBus,
        batching_config: BatchingConfig,
        *,
        activity_callback: Optional[Callable[[AudioActivityEvent], Awaitable[None]]] = None,
    ):
        self._provider_outbound_bus = provider_outbound_bus
        self._batching_config = batching_config
        self._buffers: Dict[AudioKey, List[bytes]] = defaultdict(list)
        self._participant_state: Dict[AudioKey, ParticipantState] = defaultdict(ParticipantState)
        self._lock = asyncio.Lock()
        self._activity_callback = activity_callback
        self._energy_rms_threshold = 300.0  # Rough gate for 16-bit PCM
        self._converter = PcmConverter()

    def can_handle(self, event: GatewayInputEvent) -> bool:
        payload = event.payload or {}
        if not isinstance(payload, dict):
            return False

        return payload.get("kind") == "AudioData"

    async def handle(self, event: GatewayInputEvent) -> None:
        """Handle audio envelope."""
        payload = event.payload or {}
        audio_data = payload.get("audiodata") or {}
        participant_id = None
        if isinstance(audio_data, dict):
            participant_id = audio_data.get("participantrawid")

        key: AudioKey = (event.session_id, participant_id)
        chunk_b64 = None
        if isinstance(audio_data, dict):
            chunk_b64 = audio_data.get("data") or audio_data.get("audio_b64")

        if not chunk_b64:
            logger.debug("Skipping audio envelope without audio_b64 payload")
            return

        # Decode incoming base64 to raw PCM bytes
        try:
            chunk_pcm = Base64AudioCodec.decode(chunk_b64)
        except Exception as exc:
            logger.warning("Skipping audio chunk with invalid base64: %s", exc)
            return

        # Emit lightweight activity signal if above threshold
        await self._maybe_emit_activity(event, participant_id, chunk_pcm)

        async with self._lock:
            self._buffers[key].append(chunk_pcm)
            state = self._participant_state[key]

            # Update accumulated metrics
            state.accumulated_bytes += len(chunk_pcm)
            try:
                duration_ms = AudioDurationCalculator.calculate_duration_ms_from_bytes(chunk_pcm)
                state.accumulated_duration_ms += duration_ms
            except Exception as e:
                logger.warning("Failed to calculate audio duration: %s", e)

            state.last_message_time = time.monotonic()

            # Cancel existing idle timer
            if state.idle_timer_task and not state.idle_timer_task.done():
                state.idle_timer_task.cancel()

            # Check commit conditions
            should_commit = False
            commit_reason = ""

            if state.accumulated_bytes >= self._batching_config.max_batch_bytes:
                should_commit = True
                commit_reason = f"size_threshold ({state.accumulated_bytes} >= {self._batching_config.max_batch_bytes})"
            elif state.accumulated_duration_ms >= self._batching_config.max_batch_ms:
                should_commit = True
                commit_reason = f"duration_threshold ({state.accumulated_duration_ms:.1f}ms >= {self._batching_config.max_batch_ms}ms)"

        if should_commit:
            logger.info("Auto-commit triggered for %s: %s", key, commit_reason)
            await self._flush_commit(event, key)
        else:
            # Start new idle timer
            async with self._lock:
                state = self._participant_state[key]
                state.idle_timer_task = asyncio.create_task(
                    self._idle_timeout_worker(event, key),
                    name=f"idle-timer-{event.session_id}-{participant_id}"
                )

    async def _idle_timeout_worker(self, event: GatewayInputEvent, key: AudioKey) -> None:
        """Worker task that commits buffer after idle timeout."""
        try:
            idle_timeout_sec = self._batching_config.idle_timeout_ms / 1000
            await asyncio.sleep(idle_timeout_sec)

            # Check if buffer still has data
            async with self._lock:
                if key in self._buffers and self._buffers[key]:
                    logger.info(
                        "Auto-commit triggered for %s: idle_timeout (%.1fms elapsed)",
                        key,
                        self._batching_config.idle_timeout_ms
                    )

            await self._flush_commit(event, key)

        except asyncio.CancelledError:
            logger.debug("Idle timer cancelled for %s", key)
            raise
        except Exception:
            logger.exception("Idle timeout worker failed for %s", key)

    async def _flush_commit(self, event: GatewayInputEvent, key: AudioKey) -> None:
        async with self._lock:
            # Cancel idle timer if running
            state = self._participant_state.get(key)
            if state and state.idle_timer_task and not state.idle_timer_task.done():
                state.idle_timer_task.cancel()

            raw_audio = b"".join(self._buffers.pop(key, []))

            # Clear participant state
            if key in self._participant_state:
                del self._participant_state[key]

        if not raw_audio:
            logger.debug("Skipping empty commit for %s", key)
            return

        # Generate commit_id
        commit_id = str(uuid.uuid4())

        # Create AudioRequest and publish to provider_outbound_bus
        payload = event.payload or {}
        audio_data = payload.get("audiodata") or {}
        participant_id = None
        timestamp_utc = event.received_at_utc
        if isinstance(audio_data, dict):
            participant_id = audio_data.get("participantrawid")
            timestamp_utc = audio_data.get("timestamp") or timestamp_utc
        audio_b64 = Base64AudioCodec.encode(raw_audio)
        request = ProviderInputEvent(
            commit_id=commit_id,
            session_id=event.session_id,
            participant_id=participant_id,
            b64_audio_string=audio_b64,
            metadata={"timestamp_utc": timestamp_utc, "message_id": event.event_id},
        )

        logger.info("Publishing audio request to provider - commit=%s bytes=%s", commit_id, len(raw_audio))
        await self._provider_outbound_bus.publish(request)

    async def shutdown(self) -> None:
        """Cancel all idle timers and cleanup state."""
        async with self._lock:
            tasks_to_cancel = []
            for state in self._participant_state.values():
                if state.idle_timer_task and not state.idle_timer_task.done():
                    tasks_to_cancel.append(state.idle_timer_task)

            for task in tasks_to_cancel:
                task.cancel()

        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logger.info("Cancelled %d idle timers during shutdown", len(tasks_to_cancel))

    async def _maybe_emit_activity(self, event: GatewayInputEvent, participant_id: Optional[str], chunk_pcm: bytes) -> None:
        """Compute lightweight energy metrics and emit activity callback when speech starts."""

        # Avoid expensive work if no listener
        if not self._activity_callback:
            return

        rms, peak = self._compute_rms_peak(chunk_pcm)
        frame_bytes = len(chunk_pcm)
        now = time.monotonic()

        async with self._lock:
            state = self._participant_state[(event.session_id, participant_id)]
            # Detect transition from quiet → active
            became_active = (not state.is_active) and rms >= self._energy_rms_threshold
            if became_active:
                state.is_active = True
                state.last_activity_time = now
            state.last_rms = rms

        if not became_active:
            return

        activity = AudioActivityEvent(
            session_id=event.session_id,
            participant_id=participant_id,
            rms=rms,
            peak=peak,
            timestamp_monotonic=now,
            received_at_utc=event.received_at_utc,
            frame_bytes=frame_bytes,
        )
        try:
            await self._activity_callback(activity)
        except Exception:
            logger.exception("Activity callback failed for session=%s participant=%s", event.session_id, participant_id)

    def _compute_rms_peak(self, pcm: bytes) -> tuple[float, int]:
        """Compute RMS and peak for 16-bit PCM (little-endian) leveraging shared PCM utilities."""

        if not pcm:
            return 0.0, 0

        # Default ACS capture is mono PCM16. If ACS metadata adds channels later,
        # consider plumbing that through the handler and passing channels here.
        rms = self._converter.rms_pcm16(pcm, channels=1)

        samples = np.frombuffer(pcm, dtype="<i2")
        if samples.size == 0:
            return rms, 0
        peak = int(np.max(np.abs(samples)))
        return rms, peak
