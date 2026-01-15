"""Audio turn processor for play_audio turns.

Handles streaming audio files from participants with proper timing and gap filling.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.acs_emulator.media_engine import FRAME_DURATION_MS, async_chunk_audio
from production.scenario_engine.turn_processors.base import TurnProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario


logger = logging.getLogger(__name__)


class AudioTurnProcessor(TurnProcessor):
    """Processor for play_audio turns.

    Streams audio files from participants. Audio is chunked into frames
    and sent with proper timestamps for synchronization.

    Timing orchestration (silence filling) is handled by ScenarioEngine.
    """

    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_scn_ms: int,
    ) -> int:
        """Process a play_audio turn.

        Assumes current_scn_ms is already at turn.start_at_ms (orchestrated by engine).

        The processor:
        1. Loads and chunks the audio file
        2. Streams audio frames with proper timestamps
        3. Returns updated time after playback

        Args:
            turn: The play_audio turn
            scenario: The full scenario context
            participants: List of all participants (unused, for consistency)
            current_scn_ms: Current playback position (== turn.start_at_ms)

        Returns:
            Updated current time after audio playback
        """
        # Get participant and audio file
        participant = scenario.participants[turn.participant]
        audio_path = participant.audio_files[turn.data_file]  # type: ignore[index]

        logger.debug(
            "Starting audio playback: turn=%s participant=%s file=%s at time=%s",
            turn.id, participant.name, audio_path.name, current_scn_ms
        )

        # Stream audio chunks
        chunk_count = 0
        first_chunk_wall_clock_ms = None
        last_chunk_wall_clock_ms = None

        async for offset_ms, data in async_chunk_audio(audio_path, FRAME_DURATION_MS):
            send_at_scn_ms = turn.start_at_ms + offset_ms
            chunk_count += 1
            wall_clock_ms = self.clock.now_ms()

            if chunk_count == 1:
                first_chunk_wall_clock_ms = wall_clock_ms
                logger.info(
                    f"🎤 OUTGOING AUDIO START: turn='{turn.id}', "
                    f"scenario_time={send_at_scn_ms}ms, wall_clock={wall_clock_ms}ms"
                )

            logger.debug(
                f"Sending audio chunk #{chunk_count} for '{turn.id}': "
                f"offset={offset_ms}ms, send_at={send_at_scn_ms}ms, size={len(data)} bytes"
            )

            # Send audio data
            payload = self.adapter.build_audio_message(
                participant_id=participant.name,
                pcm_bytes=data,
                timestamp_ms=send_at_scn_ms,
            )
            self.conversation_manager.register_outgoing(
                turn.id,
                payload,
                participant_id=participant.name,
                timestamp_scn_ms=send_at_scn_ms,
                audio_payload=data,
            )
            await self.ws.send_json(payload)
            await self.clock.sleep(FRAME_DURATION_MS)
            current_scn_ms = send_at_scn_ms + FRAME_DURATION_MS
            last_chunk_wall_clock_ms = wall_clock_ms

        logger.info(
            f"🎤 OUTGOING AUDIO END: turn='{turn.id}', "
            f"scenario_time={current_scn_ms}ms, wall_clock={last_chunk_wall_clock_ms}ms, "
            f"total_chunks={chunk_count}, duration={current_scn_ms - turn.start_at_ms}ms"
        )
        return current_scn_ms


__all__ = ["AudioTurnProcessor"]
