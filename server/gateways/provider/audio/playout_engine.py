from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from .acs_publisher import AcsAudioPublisher
from .playout_store import PlayoutStream

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PlayoutConfig:
    frame_ms: int = 20
    warmup_frames: int = 3


class PacedPlayoutEngine:
    """Paces outbound audio frames in real time."""

    def __init__(self, publisher: AcsAudioPublisher, config: PlayoutConfig | None = None):
        self.publisher = publisher
        self.config = config or PlayoutConfig()

    def ensure_task(self, stream: PlayoutStream) -> None:
        if stream.task and not stream.task.done():
            return
        stream.task = asyncio.create_task(self._playout_loop(stream), name=f"playout-{stream.key}")
        logger.info("Created task for stream=%s", stream.id)

    async def pause(self, stream: PlayoutStream) -> None:
        """Pause playout for this stream (keeps the background task alive)."""
        async with stream.cond:
            stream.paused = True
            buffer_bytes = len(stream.buffer)
            frame_bytes = stream.frame_bytes
            buffer_frames = buffer_bytes // frame_bytes if frame_bytes > 0 else 0
            buffer_ms = buffer_frames * self.config.frame_ms
            stream.cond.notify_all()
        logger.info(
            "PAUSE playout stream=%s buffer=%d bytes (%d frames, ~%dms) task_running=%s",
            stream.key,
            buffer_bytes,
            buffer_frames,
            buffer_ms,
            stream.task is not None and not stream.task.done(),
        )

    async def resume(self, stream: PlayoutStream) -> None:
        async with stream.cond:
            stream.paused = False
            stream.cond.notify_all()

    async def clear(self, stream: PlayoutStream) -> None:
        async with stream.cond:
            stream.buffer.clear()
            stream.cond.notify_all()

    async def shutdown(self, stream: PlayoutStream) -> None:
        logger.info("Shutting down playout stream... %s", stream.id)
        async with stream.cond:
            stream.shutdown = True
            stream.cond.notify_all()
        if stream.task:
            await asyncio.gather(stream.task, return_exceptions=True)

    async def _playout_loop(self, stream: PlayoutStream) -> None:
        logger.info("Playout loop starting... %s", stream.id)
        interval = self.config.frame_ms / 1000.0
        next_deadline: float | None = None
        try:
            while True:
                async with stream.cond:
                    if stream.paused or not stream.has_full_frame():
                        next_deadline = None

                    await stream.cond.wait_for(lambda: (
                        stream.shutdown or (not stream.paused and stream.has_full_frame())
                    ))

                    if stream.shutdown:
                        break

                    frame_bytes = stream.frame_bytes
                    chunk = bytes(stream.buffer[:frame_bytes])
                    del stream.buffer[:frame_bytes]

                await self.publisher.publish_audio_chunk(chunk)
                now = time.monotonic()
                if next_deadline is None:
                    next_deadline = now + interval
                else:
                    next_deadline += interval
                    if next_deadline < now - interval:
                        next_deadline = now + interval

                sleep_for = next_deadline - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    next_deadline = None
        except asyncio.CancelledError:
            raise
        finally:
            stream.task = None
            logger.info("Playout loop completed %s", stream.id)
