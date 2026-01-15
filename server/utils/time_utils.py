from __future__ import annotations

import time
from datetime import datetime, timezone


class MonotonicClock:
    """Utility class combining wall-clock and monotonic time helpers.

    - Wall-clock time is for logging and correlation.
    - Monotonic time is for measuring elapsed durations.
    """

    # ---- monotonic ----

    @staticmethod
    def now() -> float:
        """Return monotonic time in seconds."""
        return time.monotonic()

    @staticmethod
    def now_ms() -> int:
        """Return monotonic time in milliseconds."""
        return int(time.monotonic() * 1000)

    @staticmethod
    def elapsed_from(start: float) -> float:
        """Return elapsed seconds from a monotonic start time."""
        return time.monotonic() - start

    @staticmethod
    def elapsed_ms_from(start: float) -> int:
        """Return elapsed milliseconds from a monotonic start time."""
        return int((time.monotonic() - start) * 1000)

    # ---- wall clock ----

    @staticmethod
    def now_iso() -> str:
        """Return current UTC time in ISO-8601 format."""
        return datetime.now(timezone.utc).isoformat()


__all__ = ["MonotonicClock"]
