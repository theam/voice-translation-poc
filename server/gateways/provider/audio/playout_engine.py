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

    async def mark_done(self, stream: PlayoutStream) -> None:
        stream.done = True
        stream.data_ready.set()

    async def pause(self, stream: PlayoutStream) -> None:
        """Pause playout for this stream (stops the background task)."""
        buffer_bytes = len(stream.buffer)
        buffer_frames = buffer_bytes // stream.frame_bytes if stream.frame_bytes > 0 else 0
        buffer_ms = buffer_frames * self.config.frame_ms
        logger.info(
            "PAUSE playout stream=%s buffer=%d bytes (%d frames, ~%dms) task_running=%s",
            stream.key,
            buffer_bytes,
            buffer_frames,
            buffer_ms,
            stream.task is not None and not stream.task.done(),
        )
        stream.data_ready.set()
        if stream.task and not stream.task.done():
            stream.task.cancel()
            await asyncio.gather(stream.task, return_exceptions=True)
        stream.task = None

    async def stop(self, stream: PlayoutStream) -> None:
        # Log buffer size before discarding
        buffer_bytes = len(stream.buffer)
        buffer_frames = buffer_bytes // stream.frame_bytes if stream.frame_bytes > 0 else 0
        buffer_ms = buffer_frames * self.config.frame_ms
        logger.info(
            "STOP playout stream=%s buffer=%d bytes (%d frames, ~%dms) task_running=%s - DISCARDING AUDIO",
            stream.key,
            buffer_bytes,
            buffer_frames,
            buffer_ms,
            stream.task is not None and not stream.task.done(),
        )
        # discard buffered audio
        stream.buffer.clear()
        # prevent future waiting for warmup
        stream.done = True
        stream.data_ready.set()
        # cancel the task if running
        if stream.task and not stream.task.done():
            stream.task.cancel()
            await asyncio.gather(stream.task, return_exceptions=True)
        stream.task = None

    async def wait(self, stream: PlayoutStream) -> None:
        if stream.task:
            await asyncio.gather(stream.task, return_exceptions=True)

    async def _playout_loop(self, stream: PlayoutStream) -> None:
        logger.info(f"Playout loop starting... {stream.id}")
        warmup_frames = self.config.warmup_frames
        frame_bytes = stream.frame_bytes
        next_deadline: float | None = None
        try:
            while True:
                if not stream.done and len(stream.buffer) < warmup_frames * frame_bytes:
                    stream.data_ready.clear()
                    await stream.data_ready.wait()
                    continue

                if len(stream.buffer) >= frame_bytes:
                    chunk = bytes(stream.buffer[:frame_bytes])
                    del stream.buffer[:frame_bytes]
                    await self.publisher.publish_audio_chunk(chunk)
                    logger.debug(
                        "PUBLISHED id=%s stream=%s buf_after=%d",
                        stream.id, stream.key, len(stream.buffer)
                    )

                    now = time.monotonic()
                    interval = self.config.frame_ms / 1000
                    next_deadline = (now + interval) if next_deadline is None else next_deadline + interval
                    sleep_for = next_deadline - time.monotonic()
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue

                if stream.done:
                    break

                stream.data_ready.clear()
                await stream.data_ready.wait()
        except asyncio.CancelledError:
            raise
        finally:
            stream.task = None
            logger.info(f"Playout loop completed {stream.key}")
