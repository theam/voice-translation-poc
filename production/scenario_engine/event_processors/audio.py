"""Audio event processor for play_audio events.

Handles streaming audio files from participants with proper timing and gap filling.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from production.acs_emulator.media_engine import FRAME_DURATION_MS, async_chunk_audio
from production.scenario_engine.event_processors.base import EventProcessor

if TYPE_CHECKING:
    from production.scenario_engine.models import Event, Participant, Scenario


logger = logging.getLogger(__name__)


class AudioEventProcessor(EventProcessor):
    """Processor for play_audio events.

    Streams audio files from participants. Audio is chunked into frames
    and sent with proper timestamps for synchronization.

    Timing orchestration (silence filling) is handled by ScenarioEngine.
    """

    async def process(
        self,
        event: Event,
        scenario: Scenario,
        participants: list[Participant],
        current_time: int,
    ) -> int:
        """Process a play_audio event.

        Assumes current_time is already at event.start_at_ms (orchestrated by engine).

        The processor:
        1. Loads and chunks the audio file
        2. Streams audio frames with proper timestamps
        3. Returns updated time after playback

        Args:
            event: The play_audio event
            scenario: The full scenario context
            participants: List of all participants (unused, for consistency)
            current_time: Current playback position (== event.start_at_ms)

        Returns:
            Updated current time after audio playback
        """
        # Get participant and audio file
        participant = scenario.participants[event.participant]
        audio_path = participant.audio_files[event.audio_file]  # type: ignore[index]

        logger.debug(
            "Starting audio playback: event=%s participant=%s file=%s at time=%s",
            event.id, participant.name, audio_path.name, current_time
        )

        # Stream audio chunks
        chunk_count = 0
        async for offset_ms, data in async_chunk_audio(audio_path, FRAME_DURATION_MS):
            send_at = event.start_at_ms + offset_ms
            chunk_count += 1

            logger.debug(
                f"Sending audio chunk #{chunk_count} for '{event.id}': "
                f"offset={offset_ms}ms, send_at={send_at}ms, size={len(data)} bytes"
            )

            # Send audio data
            payload = self.adapter.build_audio_message(
                participant_id=event.id,
                pcm_bytes=data,
                timestamp_ms=send_at,
            )
            self.conversation_manager.register_outgoing(
                event.id,
                payload,
                participant_id=event.id,
            )
            await self.ws.send_json(payload)
            self.tape.add_pcm(send_at, data)
            await self.clock.sleep(FRAME_DURATION_MS)
            current_time = send_at + FRAME_DURATION_MS

        logger.debug(
            "Completed audio event: event=%s participant=%s final_time=%s",
            event.id, participant.name, current_time
        )
        return current_time


__all__ = ["AudioEventProcessor"]
