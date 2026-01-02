from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..gateways.acs.audio import AudioActivityEvent

logger = logging.getLogger(__name__)


class SessionActivity:
    """Manages session-scoped activity sink and worker lifecycle."""

    def __init__(
        self,
        session_id: str,
        *,
        listener: Optional[callable] = None,
    ):
        self.session_id = session_id
        self._events: asyncio.Queue[AudioActivityEvent] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._listener = listener

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        async def worker():
            while True:
                try:
                    event = await self._events.get()
                    logger.debug(
                        "Activity detected session=%s participant=%s rms=%.1f peak=%s frame=%s",
                        event.session_id,
                        event.participant_id,
                        event.rms,
                        event.peak,
                        event.frame_bytes,
                    )
                    if self._listener:
                        await self._listener(event)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("Activity worker error (session=%s)", self.session_id)

        self._task = asyncio.create_task(worker(), name=f"activity-worker-{self.session_id}")

    async def sink(self, event: AudioActivityEvent) -> None:
        await self._events.put(event)

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
