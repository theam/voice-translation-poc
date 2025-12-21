from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...config import BatchingConfig
from ...models.envelope import Envelope
from ...core.event_bus import EventBus
from ...models.messages import AudioRequest
from ...services.audio_duration import AudioDurationCalculator

logger = logging.getLogger(__name__)


AudioKey = Tuple[str, str | None]


@dataclass
class ParticipantState:
    """Tracks batching state for a single participant."""
    accumulated_bytes: int = 0  # Base64-encoded byte count
    accumulated_duration_ms: float = 0.0  # Audio duration in milliseconds
    last_message_time: float = 0.0  # Monotonic time of last audio chunk
    idle_timer_task: Optional[asyncio.Task] = None  # Async task for idle timeout


class AudioMessageHandler:
    """Consumes audio envelopes, buffers audio, and dispatches to provider."""

    def __init__(
        self,
        provider_outbound_bus: EventBus,
        batching_config: BatchingConfig
    ):
        self._provider_outbound_bus = provider_outbound_bus
        self._batching_config = batching_config
        self._buffers: Dict[AudioKey, List[bytes]] = defaultdict(list)
        self._participant_state: Dict[AudioKey, ParticipantState] = defaultdict(ParticipantState)
        self._lock = asyncio.Lock()

    async def handle(self, envelope: Envelope) -> None:
        """Handle audio envelope."""
        key: AudioKey = (envelope.session_id, envelope.participant_id)
        chunk_b64 = envelope.payload.get("audio_b64")

        if not chunk_b64:
            logger.debug("Skipping audio envelope without audio_b64 payload")
            return

        chunk_bytes = chunk_b64.encode()
        async with self._lock:
            self._buffers[key].append(chunk_bytes)
            state = self._participant_state[key]

            # Update accumulated metrics
            state.accumulated_bytes += len(chunk_bytes)
            try:
                duration_ms = AudioDurationCalculator.calculate_duration_ms(chunk_b64)
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
            await self._flush_commit(envelope, key)
        else:
            # Start new idle timer
            async with self._lock:
                state = self._participant_state[key]
                state.idle_timer_task = asyncio.create_task(
                    self._idle_timeout_worker(envelope, key),
                    name=f"idle-timer-{envelope.session_id}-{envelope.participant_id}"
                )

    async def _idle_timeout_worker(self, envelope: Envelope, key: AudioKey) -> None:
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

            await self._flush_commit(envelope, key)

        except asyncio.CancelledError:
            logger.debug("Idle timer cancelled for %s", key)
            raise
        except Exception:
            logger.exception("Idle timeout worker failed for %s", key)

    async def _flush_commit(self, envelope: Envelope, key: AudioKey) -> None:
        async with self._lock:
            # Cancel idle timer if running
            state = self._participant_state.get(key)
            if state and state.idle_timer_task and not state.idle_timer_task.done():
                state.idle_timer_task.cancel()

            audio_chunks = b"".join(self._buffers.pop(key, []))

            # Clear participant state
            if key in self._participant_state:
                del self._participant_state[key]

        if not audio_chunks:
            logger.debug("Skipping empty commit for %s", key)
            return

        # Generate commit_id if not present
        commit_id = envelope.commit_id or str(uuid.uuid4())

        # Create AudioRequest and publish to provider_outbound_bus
        request = AudioRequest(
            commit_id=commit_id,
            session_id=envelope.session_id,
            participant_id=envelope.participant_id,
            audio_data=audio_chunks,
            metadata={"timestamp_utc": envelope.timestamp_utc, "message_id": envelope.message_id},
        )

        logger.info("Publishing audio request to provider: commit=%s bytes=%s", commit_id, len(audio_chunks))
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
