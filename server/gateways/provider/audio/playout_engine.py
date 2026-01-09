from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .acs_publisher import AcsAudioPublisher
from .playout_store import PlayoutState


@dataclass(frozen=True)
class PlayoutConfig:
    frame_ms: int = 20
    warmup_frames: int = 3


class PacedPlayoutEngine:
    """Paces outbound audio frames in real time."""

    def __init__(self, publisher: AcsAudioPublisher, config: PlayoutConfig | None = None):
        self.publisher = publisher
        self.config = config or PlayoutConfig()

    def ensure_task(self, key: str, state: PlayoutState) -> None:
        if state.task and not state.task.done():
            return
        state.task = asyncio.create_task(self._playout_loop(key, state), name=f"playout-{key}")

    async def mark_done(self, state: PlayoutState) -> None:
        state.done = True
        state.data_ready.set()

    async def cancel(self, key: str, state: PlayoutState) -> None:
        state.done = True
        state.data_ready.set()
        if state.task and not state.task.done():
            state.task.cancel()
            await asyncio.gather(state.task, return_exceptions=True)
        state.task = None

    async def wait(self, state: PlayoutState) -> None:
        if state.task:
            await asyncio.gather(state.task, return_exceptions=True)

    async def _playout_loop(self, key: str, state: PlayoutState) -> None:
        warmup_frames = self.config.warmup_frames
        frame_bytes = state.frame_bytes
        next_deadline: float | None = None
        try:
            while True:
                if not state.done and len(state.buffer) < warmup_frames * frame_bytes:
                    state.data_ready.clear()
                    await state.data_ready.wait()
                    continue

                if len(state.buffer) >= frame_bytes:
                    chunk = bytes(state.buffer[:frame_bytes])
                    del state.buffer[:frame_bytes]
                    await self.publisher.publish_audio_chunk(chunk)

                    now = time.monotonic()
                    interval = self.config.frame_ms / 1000
                    next_deadline = (now + interval) if next_deadline is None else next_deadline + interval
                    sleep_for = next_deadline - time.monotonic()
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue

                if state.done:
                    break

                state.data_ready.clear()
                await state.data_ready.wait()
        except asyncio.CancelledError:
            raise
        finally:
            state.task = None
