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
        current_time: int,
    ) -> int:
        """Process a play_audio turn.

        Assumes current_time is already at turn.start_at_ms (orchestrated by engine).

        The processor:
        1. Loads and chunks the audio file
        2. Streams audio frames with proper timestamps
        3. Returns updated time after playback

        Args:
            turn: The play_audio turn
            scenario: The full scenario context
            participants: List of all participants (unused, for consistency)
            current_time: Current playback position (== turn.start_at_ms)

        Returns:
            Updated current time after audio playback
        """
        # Get participant and audio file
        participant = scenario.participants[turn.participant]
        audio_path = participant.audio_files[turn.audio_file]  # type: ignore[index]

        logger.debug(
            "Starting audio playback: turn=%s participant=%s file=%s at time=%s",
            turn.id, participant.name, audio_path.name, current_time
        )

        # Stream audio chunks
        chunk_count = 0
        first_chunk_wall_clock = None
        last_chunk_wall_clock = None

        async for offset_ms, data in async_chunk_audio(audio_path, FRAME_DURATION_MS):
            send_at = turn.start_at_ms + offset_ms
            chunk_count += 1
            wall_clock_ms = self.clock.now_ms()

            if chunk_count == 1:
                first_chunk_wall_clock = wall_clock_ms
                logger.info(
                    f"🎤 OUTGOING AUDIO START: turn='{turn.id}', "
                    f"scenario_time={send_at}ms, wall_clock={wall_clock_ms}ms"
                )

            logger.debug(
                f"Sending audio chunk #{chunk_count} for '{turn.id}': "
                f"offset={offset_ms}ms, send_at={send_at}ms, size={len(data)} bytes"
            )

            # Send audio data
            payload = self.adapter.build_audio_message(
                participant_id=turn.id,
                pcm_bytes=data,
                timestamp_ms=send_at,
            )
            # Register with scenario timeline timestamp (send_at), not wall-clock
            # This ensures last_outbound_ms matches when audio actually plays in the tape
            self.conversation_manager.register_outgoing(
                turn.id,
                payload,
                participant_id=turn.id,
                timestamp_ms=send_at,  # Use scenario timeline!
            )
            await self.ws.send_json(payload)
            self.tape.add_pcm(send_at, data)
            await self.clock.sleep(FRAME_DURATION_MS)
            current_time = send_at + FRAME_DURATION_MS
            last_chunk_wall_clock = wall_clock_ms

        logger.info(
            f"🎤 OUTGOING AUDIO END: turn='{turn.id}', "
            f"scenario_time={current_time}ms, wall_clock={last_chunk_wall_clock}ms, "
            f"total_chunks={chunk_count}, duration={current_time - turn.start_at_ms}ms"
        )
        return current_time


__all__ = ["AudioTurnProcessor"]
