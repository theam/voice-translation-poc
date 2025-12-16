"""Silence turn processor for explicit silence turns.

Handles returning the time after a specified silence duration.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.scenario_engine.turn_processors.base import TurnProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario


logger = logging.getLogger(__name__)


class SilenceTurnProcessor(TurnProcessor):
    """Processor for silence turns.

    Returns the target time after a specified silence duration.
    The actual silence streaming is handled by the engine's orchestration.

    This is useful for testing timing, simulating pauses, or creating gaps
    in conversation flow.
    """

    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_time: int,
    ) -> int:
        """Process a silence turn.

        Assumes current_time is already at turn.start_at_ms (orchestrated by engine).

        Simply calculates and returns the target time after the silence duration.
        The engine will handle streaming silence to reach this time.

        Note: The duration is stored in turn.audio_file as an integer
        representing milliseconds (this is a legacy field reuse).

        Args:
            turn: The silence turn
            scenario: The full scenario context (unused)
            participants: List of all participants (unused, for consistency)
            current_time: Current playback position (== turn.start_at_ms)

        Returns:
            Target time after silence duration
        """
        duration = int(turn.audio_file or 0)
        target_time = current_time + duration

        logger.debug(
            "Silence turn: turn=%s duration=%sms current=%s target=%s",
            turn.id, duration, current_time, target_time
        )

        return target_time


__all__ = ["SilenceTurnProcessor"]
