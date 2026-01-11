from __future__ import annotations

import asyncio
import logging
from collections import deque
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class OverflowPolicy(str, Enum):
    DROP_OLDEST = "DROP_OLDEST"
    DROP_NEWEST = "DROP_NEWEST"


class BoundedQueue(Generic[T]):
    """Bounded queue with explicit overflow behavior."""

    def __init__(self, maxsize: int, overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST):
        self._queue: deque[T] = deque()
        self._maxsize = maxsize
        self._overflow_policy = overflow_policy
        self._not_empty = asyncio.Condition()

    def __len__(self) -> int:
        return len(self._queue)

    def qsize(self) -> int:
        """Return current queue size."""
        return len(self._queue)

    async def clear(self) -> int:
        """
        Remove all queued items.
        Returns the number of items removed.
        """
        async with self._not_empty:
            n = len(self._queue)
            self._queue.clear()
            # Wake up any producers or consumers waiting on the condition
            self._not_empty.notify_all()
        return n

    async def put(self, item: T) -> bool:
        if len(self._queue) < self._maxsize:
            self._queue.append(item)
            await self._notify()
            return True

        if self._overflow_policy == OverflowPolicy.DROP_OLDEST:
            dropped = self._queue.popleft()
            logger.warning("Dropped oldest item due to overflow: %s", dropped)
            self._queue.append(item)
            await self._notify()
            return False
        if self._overflow_policy == OverflowPolicy.DROP_NEWEST:
            logger.warning("Dropped newest item due to overflow: %s", item)
            return False
        raise ValueError(f"Unknown overflow policy {self._overflow_policy}")

    async def get(self) -> T:
        async with self._not_empty:
            while not self._queue:
                await self._not_empty.wait()
            item = self._queue.popleft()
            self._not_empty.notify()
        return item

    async def _notify(self) -> None:
        async with self._not_empty:
            self._not_empty.notify()
