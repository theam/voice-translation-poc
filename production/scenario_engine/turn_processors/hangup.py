"""Hangup turn processor for call termination turns.

Handles sending hangup control messages for participants.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.scenario_engine.turn_processors.base import TurnProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario


logger = logging.getLogger(__name__)


class HangupTurnProcessor(TurnProcessor):
    """Processor for hangup turns.

    Sends a hangup control message for a specific participant,
    simulating call termination. This is useful for testing
    mid-call disconnections and cleanup logic.

    Timing orchestration (silence filling) is handled by ScenarioEngine.
    """

    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_scn_ms: int,
    ) -> int:
        """Process a hangup turn.

        Assumes current_scn_ms is already at turn.start_at_ms (orchestrated by engine).

        Sends hangup control message for the participant.
        Returns unchanged current time since hangup is instantaneous.

        Args:
            turn: The hangup turn
            scenario: The full scenario context (unused)
            participants: List of all participants (unused, for consistency)
            current_scn_ms: Current playback position (== turn.start_at_ms)

        Returns:
            Unchanged current time (hangup is instantaneous)
        """
        logger.debug(
            "Sending hangup: turn=%s participant=%s time=%s",
            turn.id, turn.participant, current_scn_ms
        )

        # Send hangup control message
        payload = self.adapter.build_control_message("hangup", participant_id=turn.participant)
        self.conversation_manager.register_outgoing(
            turn.id,
            payload,
            participant_id=turn.participant,
            timestamp_scn_ms=current_scn_ms,
        )
        await self.ws.send_json(
            payload
        )

        logger.debug(
            "Completed hangup turn: turn=%s participant=%s",
            turn.id, turn.participant
        )
        return current_scn_ms


__all__ = ["HangupTurnProcessor"]
