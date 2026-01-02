from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..gateways.acs.audio import AudioActivityEvent
from ..models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


class TurnState(str, Enum):
    IDLE = "idle"
    SPEAKING_OUT = "speaking_out"
    LISTENING_IN = "listening_in"
    INTERRUPTING = "interrupting"
    CANCELLED = "cancelled"


@dataclass
class StreamContext:
    stream_key: str
    participant_id: Optional[str]
    started_at: float = field(default_factory=time.monotonic)


class TurnController:
    """
    Minimal turn/orchestration layer for barge-in detection (phase 2).

    Responsibilities:
    - Track when outbound audio is active (per stream)
    - Observe inbound activity events to detect potential barge-in
    - Emit structured debug logs and counters (no provider/ACS side-effects yet)
    """

    def __init__(
        self,
        session_id: str,
        *,
        cooldown_ms: int = 250,
        on_barge_in: Optional[callable] = None,
    ):
        self.session_id = session_id
        self.state: TurnState = TurnState.IDLE
        self.active_stream: Optional[StreamContext] = None
        self.cooldown_ms = cooldown_ms
        self._debounce_until = 0.0
        self._lock = asyncio.Lock()
        self.stats = {
            "barge_in_candidates": 0,
            "barge_in_suppressed": 0,
            "outbound_started": 0,
            "outbound_completed": 0,
            "barge_in_handled": 0,
        }
        self._on_barge_in = on_barge_in
        self._last_barge_stream: Optional[str] = None

    async def on_outbound_start(self, event: ProviderOutputEvent, stream_key: str) -> None:
        async with self._lock:
            self.state = TurnState.SPEAKING_OUT
            self.active_stream = StreamContext(stream_key=stream_key, participant_id=event.participant_id)
            self.stats["outbound_started"] += 1
            logger.debug(
                "TurnController: outbound start session=%s participant=%s stream=%s",
                self.session_id,
                event.participant_id,
                stream_key,
            )

    async def on_outbound_end(self, event: ProviderOutputEvent, stream_key: str) -> None:
        async with self._lock:
            if self.active_stream and self.active_stream.stream_key == stream_key:
                self.active_stream = None
            self.state = TurnState.LISTENING_IN
            self.stats["outbound_completed"] += 1
            logger.debug(
                "TurnController: outbound end session=%s participant=%s stream=%s",
                self.session_id,
                event.participant_id,
                stream_key,
            )

    async def on_inbound_activity(self, event: AudioActivityEvent) -> None:
        now = time.monotonic()
        async with self._lock:
            if now < self._debounce_until:
                self.stats["barge_in_suppressed"] += 1
                return
            if self.state != TurnState.SPEAKING_OUT or not self.active_stream:
                return

            # Ignore self-audio if participant IDs match
            if self.active_stream.participant_id and event.participant_id == self.active_stream.participant_id:
                return

            stream_key = self.active_stream.stream_key
            self.state = TurnState.INTERRUPTING
            self.stats["barge_in_candidates"] += 1
            self._debounce_until = now + (self.cooldown_ms / 1000.0)
            self._last_barge_stream = stream_key

        # Fire callback outside the lock to avoid deadlocks
        logger.info(
            "TurnController: barge-in candidate session=%s from=%s active_stream=%s rms=%.1f peak=%s",
            self.session_id,
            event.participant_id,
            stream_key,
            event.rms,
            event.peak,
        )
        if self._on_barge_in:
            try:
                await self._on_barge_in(event, stream_key)
            except Exception:
                logger.exception("TurnController on_barge_in callback failed")

    async def mark_barge_handled(self) -> None:
        async with self._lock:
            self.stats["barge_in_handled"] += 1
            self.state = TurnState.LISTENING_IN
            self.active_stream = None
            self._last_barge_stream = None

    async def shutdown(self) -> None:
        async with self._lock:
            self.state = TurnState.IDLE
            self.active_stream = None
            logger.info("TurnController stats session=%s %s", self.session_id, self.stats)
