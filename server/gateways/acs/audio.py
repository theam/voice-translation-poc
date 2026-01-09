from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...config import BatchingConfig, LOG_EVERY_N_ITEMS
from ...audio import Base64AudioCodec, PcmConverter
from ...models.gateway_input_event import GatewayInputEvent
from ...core.event_bus import EventBus
from ...models.provider_events import ProviderInputEvent
from ...services.audio_duration import AudioDurationCalculator
from ...session.input_state import InputState
from ...utils.time_utils import MonotonicClock

logger = logging.getLogger(__name__)


AudioKey = Tuple[str, str | None]


@dataclass
class ParticipantState:
    """Tracks batching state for a single participant."""
    accumulated_bytes: int = 0  # Raw PCM byte count
    accumulated_duration_ms: float = 0.0  # Audio duration in milliseconds
    last_message_time: float = 0.0  # Monotonic time of last audio chunk
    idle_timer_task: Optional[asyncio.Task] = None  # Async task for idle timeout


class AudioMessageHandler:
    """Consumes audio envelopes, buffers audio, and dispatches to provider."""

    SILENCE_RMS_THRESHOLD = 50.0

    def __init__(
        self,
        provider_outbound_bus: EventBus,
        batching_config: BatchingConfig,
        session_metadata: Optional[Dict[str, Any]] = None,
        pcm_converter: Optional[PcmConverter] = None,
        input_state: Optional[InputState] = None,
    ):
        self._provider_outbound_bus = provider_outbound_bus
        self._batching_config = batching_config
        self._session_metadata = session_metadata or {}
        self._pcm_converter = pcm_converter or PcmConverter()
        self._input_state = input_state
        self._buffers: Dict[AudioKey, List[bytes]] = defaultdict(list)
        self._participant_state: Dict[AudioKey, ParticipantState] = defaultdict(ParticipantState)
        self._lock = asyncio.Lock()

        # Commit tracking for periodic logging
        self._commit_count = 0
        self._total_commits_bytes = 0
        # TODO: Should we delete duration calculation for performance?
        self._total_commits_duration_ms = 0.0

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
            should_commit = (
                state.accumulated_bytes >= self._batching_config.max_batch_bytes
                or state.accumulated_duration_ms >= self._batching_config.max_batch_ms
            )

        if should_commit:
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
        rms = self._pcm_converter.rms_pcm16(raw_audio, self._resolve_channels())
        is_silence = rms < self.SILENCE_RMS_THRESHOLD
        await self._update_input_state(is_silence, participant_id)
        audio_b64 = Base64AudioCodec.encode(raw_audio)
        request = ProviderInputEvent(
            commit_id=commit_id,
            session_id=event.session_id,
            participant_id=participant_id,
            b64_audio_string=audio_b64,
            metadata={
                "timestamp_utc": timestamp_utc,
                "message_id": event.event_id,
                "rms_pcm16": rms,
                "is_silence": is_silence,
            },
        )

        # Track commit stats for periodic logging
        self._commit_count += 1
        self._total_commits_bytes += len(raw_audio)

        # Calculate duration for this commit
        try:
            duration_ms = AudioDurationCalculator.calculate_duration_ms_from_bytes(raw_audio)
            self._total_commits_duration_ms += duration_ms
        except Exception:
            pass  # Ignore duration calculation errors for logging

        # Log progress every N commits
        if self._commit_count % LOG_EVERY_N_ITEMS == 0:
            logger.info(
                "audio_commits_progress total_commits=%d total_bytes=%d total_duration_ms=%.1f",
                self._commit_count,
                self._total_commits_bytes,
                self._total_commits_duration_ms,
            )

        await self._provider_outbound_bus.publish(request)

    async def _update_input_state(self, is_silence: bool, participant_id: Optional[str]) -> None:
        if not self._input_state:
            return
        now_ms = MonotonicClock.now_ms()
        old_status = self._input_state.status
        if is_silence:
            transitioned = await self._input_state.on_silence_detected(now_ms)
        else:
            transitioned = await self._input_state.on_voice_detected(now_ms)
        if transitioned:
            logger.info(
                "input_state_changed from=%s to=%s participant_id=%s",
                old_status,
                self._input_state.status,
                participant_id,
            )

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

    async def flush(self, participant_id: Optional[str] = None) -> None:
        """Clear buffered audio (best effort, used by control plane)."""
        async with self._lock:
            tasks_to_cancel = []
            keys = list(self._buffers.keys())
            for key in keys:
                _, pid = key
                if participant_id is not None and pid != participant_id:
                    continue
                state = self._participant_state.pop(key, None)
                if state and state.idle_timer_task and not state.idle_timer_task.done():
                    state.idle_timer_task.cancel()
                    tasks_to_cancel.append(state.idle_timer_task)
                self._buffers.pop(key, None)

        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logger.info("Flushed %d participant buffers (participant=%s)", len(tasks_to_cancel), participant_id)

    def _resolve_channels(self) -> int:
        channels = 1
        format_info = self._session_metadata.get("acs_audio", {}).get("format", {})
        if isinstance(format_info, dict):
            channels = format_info.get("channels") or channels
        try:
            channels = int(channels)
        except (TypeError, ValueError):
            channels = 1
        if channels not in (1, 2):
            channels = 1
        return channels
