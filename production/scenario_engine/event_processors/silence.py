"""Silence event processor for explicit silence events.

Handles returning the time after a specified silence duration.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.scenario_engine.event_processors.base import EventProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import Event, Participant, Scenario


logger = logging.getLogger(__name__)


class SilenceEventProcessor(EventProcessor):
    """Processor for silence events.

    Returns the target time after a specified silence duration.
    The actual silence streaming is handled by the engine's orchestration.

    This is useful for testing timing, simulating pauses, or creating gaps
    in conversation flow.
    """

    async def process(
        self,
        event: Event,
        scenario: Scenario,
        participants: list[Participant],
        current_time: int,
    ) -> int:
        """Process a silence event.

        Assumes current_time is already at event.start_at_ms (orchestrated by engine).

        Simply calculates and returns the target time after the silence duration.
        The engine will handle streaming silence to reach this time.

        Note: The duration is stored in event.audio_file as an integer
        representing milliseconds (this is a legacy field reuse).

        Args:
            event: The silence event
            scenario: The full scenario context (unused)
            participants: List of all participants (unused, for consistency)
            current_time: Current playback position (== event.start_at_ms)

        Returns:
            Target time after silence duration
        """
        duration = int(event.audio_file or 0)
        target_time = current_time + duration

        logger.debug(
            "Silence event: event=%s duration=%sms current=%s target=%s",
            event.id, duration, current_time, target_time
        )

        return target_time


__all__ = ["SilenceEventProcessor"]
