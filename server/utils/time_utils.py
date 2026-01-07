from __future__ import annotations

import time


class MonotonicClock:
    """Utility class for monotonic timestamps."""

    @staticmethod
    def now() -> float:
        """Return monotonic time in seconds."""
        return time.monotonic()

    @staticmethod
    def now_ms() -> int:
        """Return monotonic time in milliseconds."""
        return int(time.monotonic() * 1000)


__all__ = ["MonotonicClock"]
