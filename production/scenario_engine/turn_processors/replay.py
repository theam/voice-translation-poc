"""Wire log replay turn processor.

Replays wire log messages with exact timing from original recording.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from production.scenario_engine.turn_processors.base import TurnProcessor
from production.wire_log.parser import WireLogParser

if TYPE_CHECKING:
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario


logger = logging.getLogger(__name__)


class ReplayWireLogTurnProcessor(TurnProcessor):
    """Processor for replay_wire_log turns.

    Replays messages from wire log with exact timing preservation.
    Sends raw messages from wire log without modification.

    CRITICAL: Does NOT add silence frames - preserves exact wire log timing.
    """

    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_scn_ms: int,
    ) -> int:
        """Process a replay_wire_log turn.

        Reads wire log file from turn.data_file, parses inbound messages,
        and sends them with exact timing from original recording.
        Timing is preserved by calculating deltas between message timestamps.

        Args:
            turn: The replay_wire_log turn with data_file pointing to wire log
            scenario: The full scenario context
            participants: List of all participants (unused)
            current_scn_ms: Current playback position (should be 0)

        Returns:
            Updated current time after replay (timestamp of last message)
        """
        if not turn.data_file:
            logger.error("No data_file specified for replay turn %s", turn.id)
            return current_scn_ms

        # Load and parse wire log file
        wire_log_path = Path(turn.data_file)
        if not wire_log_path.exists():
            logger.error("Wire log file not found: %s", wire_log_path)
            return current_scn_ms

        logger.info("Loading wire log from: %s", wire_log_path.name)
        parser = WireLogParser()
        all_messages = parser.load(wire_log_path)

        # Filter messages for replay (inbound only, exclude control.test*)
        messages = parser.filter_for_replay(all_messages)

        # Sort by scenario timestamp
        messages.sort(key=lambda m: m.scenario_timestamp_ms or 0)

        logger.info(
            "📋 Replaying %d messages (filtered from %d total)",
            len(messages),
            len(all_messages)
        )

        prev_timestamp_scn_ms = 0
        audio_chunk_count = 0

        for i, msg in enumerate(messages):
            # Calculate sleep time based on timestamp delta
            current_timestamp_scn_ms = msg.scenario_timestamp_ms or 0
            delta_ms = current_timestamp_scn_ms - prev_timestamp_scn_ms

            if delta_ms > 0:
                # Sleep for the time difference (respecting acceleration)
                await self.clock.sleep(delta_ms)

            # Send raw message from wire log (preserve exact format)
            if msg.raw_message:
                message_payload = msg.raw_message.get("message", {})
                await self.ws.send_json(message_payload)

                # Only track audio messages in conversation timeline
                if msg.kind == "AudioData" and msg.audio_data:
                    self.conversation_manager.register_outgoing(
                        turn.id,
                        message_payload,
                        participant_id=msg.participant_id or "unknown",
                        timestamp_scn_ms=current_timestamp_scn_ms,
                        audio_payload=msg.audio_data,
                    )
                    audio_chunk_count += 1

                # Log progress
                if i % 100 == 0 or i == len(messages) - 1:
                    logger.debug(
                        "Sent message %d/%d: kind=%s, timestamp=%dms, delta=%dms",
                        i + 1,
                        len(messages),
                        msg.kind,
                        current_timestamp_scn_ms,
                        delta_ms,
                    )

            prev_timestamp_scn_ms = current_timestamp_scn_ms

        logger.info(
            "✅ Wire log replay complete: %d messages sent (%d audio chunks), final_time=%dms",
            len(messages),
            audio_chunk_count,
            prev_timestamp_scn_ms,
        )

        # Return final timestamp
        return prev_timestamp_scn_ms


__all__ = ["ReplayWireLogTurnProcessor"]
