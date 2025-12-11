"""Time and pacing helpers for the scenario engine."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class Clock:
    """A simple controllable clock for pacing scenario events."""

    acceleration: float = 1.0
    time_fn: Callable[[], float] = time.monotonic

    def now_ms(self) -> int:
        return int(self.time_fn() * 1000)

    async def sleep(self, duration_ms: int) -> None:
        await asyncio.sleep(duration_ms / 1000.0 / self.acceleration)


__all__ = ["Clock"]
