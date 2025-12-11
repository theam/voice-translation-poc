"""Hangup event processor for call termination events.

Handles sending hangup control messages for participants.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.scenario_engine.event_processors.base import EventProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import Event, Participant, Scenario


logger = logging.getLogger(__name__)


class HangupEventProcessor(EventProcessor):
    """Processor for hangup events.

    Sends a hangup control message for a specific participant,
    simulating call termination. This is useful for testing
    mid-call disconnections and cleanup logic.

    Timing orchestration (silence filling) is handled by ScenarioEngine.
    """

    async def process(
        self,
        event: Event,
        scenario: Scenario,
        participants: list[Participant],
        current_time: int,
    ) -> int:
        """Process a hangup event.

        Assumes current_time is already at event.start_at_ms (orchestrated by engine).

        Sends hangup control message for the participant.
        Returns unchanged current time since hangup is instantaneous.

        Args:
            event: The hangup event
            scenario: The full scenario context (unused)
            participants: List of all participants (unused, for consistency)
            current_time: Current playback position (== event.start_at_ms)

        Returns:
            Unchanged current time (hangup is instantaneous)
        """
        logger.debug(
            "Sending hangup: event=%s participant=%s time=%s",
            event.id, event.participant, current_time
        )

        # Send hangup control message
        payload = self.adapter.build_control_message("hangup", participant_id=event.participant)
        self.conversation_manager.register_outgoing(
            event.id,
            payload,
            participant_id=event.participant,
        )
        await self.ws.send_json(
            payload
        )

        logger.debug(
            "Completed hangup event: event=%s participant=%s",
            event.id, event.participant
        )
        return current_time


__all__ = ["HangupEventProcessor"]
