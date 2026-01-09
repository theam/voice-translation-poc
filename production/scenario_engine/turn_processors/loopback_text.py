"""Loopback text turn processor for loopback_text turns.

Simulates the translation service response by creating both audio and text
messages that represent what a real translation service would return.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.scenario_engine.turn_processors.base import TurnProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario


logger = logging.getLogger(__name__)


class LoopbackTextTurnProcessor(TurnProcessor):
    """Processor for loopback_text turns.

    Creates simulated translation service responses by sending:
    1. An audio message with silent audio (represents translated audio)
    2. A text delta message with expected translation (represents translated text)

    These messages are echoed back by the loopback client and processed by
    the conversation manager to evaluate translation quality.

    Unlike play_text turns, loopback_text turns do NOT send outgoing audio
    to the translation service. Instead, they directly create the expected
    response messages that simulate what the service would return.
    """

    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_scn_ms: int,
    ) -> int:
        """Process a loopback_text turn.

        Creates and sends simulated translation service responses:
        1. Silent audio message (simulates translated audio from service)
        2. Text delta message (simulates translated text from service)

        Args:
            turn: The loopback_text turn with text and expected_text fields
            scenario: The full scenario context
            participants: List of all participants
            current_scn_ms: Current playback position (== turn.start_at_ms)

        Returns:
            Current time (loopback messages are instantaneous)

        Raises:
            ValueError: If turn.expected_text is not provided
        """
        if not turn.expected_text:
            raise ValueError(
                f"loopback_text turn '{turn.id}' missing text field. "
                f"Loopback turns require text to simulate translation responses."
            )

        participant = scenario.participants[turn.participant]

        logger.info(
            f"Creating loopback response: turn={turn.id} participant={participant.name} "
             f"text={len(turn.expected_text)}chars"
        )

        # 1. Create silent audio message (simulates translated audio from service)
        # This represents what the translation service would send as synthesized audio
        silent_audio = b'\x00' * 320  # 16-bit PCM, 10ms at 16kHz

        audio_payload = self.adapter.build_audio_message(
            participant_id=turn.id,
            pcm_bytes=silent_audio,
            timestamp_ms=current_scn_ms,
            silent=True,
        )

        # Send audio message (will be echoed back by loopback client)
        await self.ws.send_json(audio_payload)

        # 2. Create text delta message (simulates translated text from service)
        # This represents the translation.text_delta messages the service sends
        text_delta_payload = {
            "type": "translation.text_delta",
            "participant_id": turn.id,
            "source_language": turn.source_language or participant.source_language,
            "target_language": turn.expected_language or participant.target_language,
            "delta": turn.text,
        }

        # Register as outgoing (for conversation tracking)
        # Note: We register the text delta, not the audio, since that's what metrics evaluate
        self.conversation_manager.register_outgoing(
            turn.id,
            text_delta_payload,
            participant_id=turn.id,
            timestamp_scn_ms=current_scn_ms,
        )

        # Send text delta message (will be echoed back by loopback client)
        await self.ws.send_json(text_delta_payload)

        logger.info(
            f"Loopback response sent: turn={turn.id} audio={len(silent_audio)}bytes "
            f"text_delta={len(turn.expected_text)}chars"
        )

        # Loopback messages are instantaneous (no duration)
        return current_scn_ms


__all__ = ["LoopbackTextTurnProcessor"]
