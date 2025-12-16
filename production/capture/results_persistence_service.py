"""Service to manage persisting scenario results to disk."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from bson import ObjectId

from production.capture.audio_sink import AudioSink, AUDIO_EVENT_TYPES
from production.capture.collector import EventCollector
from production.capture.conversation_tape import ConversationTape
from production.capture.raw_log_sink import RawLogSink
from production.capture.transcript_sink import TranscriptSink, TEXT_EVENT_TYPES

logger = logging.getLogger(__name__)


class ResultsPersistenceService:
    """Service for persisting scenario execution results to disk.

    Coordinates writing audio events, transcripts, raw messages, and call mix
    to structured directories using specialized sink components.
    """

    def __init__(self, base_output_dir: Path, scenario_id: str, evaluation_run_id: ObjectId) -> None:
        """Initialize the persistence service.

        Creates the output directory structure based on scenario and evaluation run IDs.
        Also creates the websocket log sink for capturing WebSocket traffic.

        Args:
            base_output_dir: Base output directory from config
            scenario_id: Unique identifier for the scenario
            evaluation_run_id: Unique identifier for the evaluation run
        """
        self.output_root = base_output_dir  / str(evaluation_run_id) /scenario_id
        self.output_root.mkdir(parents=True, exist_ok=True)

        # Create websocket log sink for capturing WebSocket traffic
        self._websocket_sink = RawLogSink(self.output_root, filename="websocket.log")

        logger.info(
            f"Initialized ResultsPersistenceService: "
            f"scenario_id={scenario_id}, evaluation_run_id={evaluation_run_id}, "
            f"output_root={self.output_root}"
        )

    def get_websocket_sink(self) -> RawLogSink:
        """Get the websocket log sink for passing to WebSocket client.

        Returns:
            RawLogSink configured for websocket.log
        """
        return self._websocket_sink

    def persist_results(
        self,
        collector: EventCollector,
        raw_messages: List[dict],
        tape: ConversationTape
    ) -> None:
        """Persist all scenario results to disk.

        Writes:
        - Individual translated audio files (audio/*.wav)
        - Mixed call audio (audio/call_mix.wav)
        - Transcript events (transcripts.json)
        - Raw WebSocket messages (sut_messages.log)

        Args:
            collector: Event collector with all collected events
            raw_messages: List of raw WebSocket messages
            tape: Conversation tape with mixed audio
        """
        logger.info(
            f"Starting results persistence to {self.output_root} "
            f"(events: {len(collector.events)}, raw_messages: {len(raw_messages)}, "
            f"sample_rate: {tape.sample_rate}Hz)"
        )

        # Persist audio events and call mix
        audio_sink = AudioSink(self.output_root, sample_rate=tape.sample_rate)
        audio_events = [e for e in collector.events if e.event_type in AUDIO_EVENT_TYPES]
        logger.debug(f"Writing {len(audio_events)} audio events")
        audio_sink.write_audio_events(audio_events)

        logger.debug("Writing call mix audio")
        audio_sink.write_call_mix(tape)

        # Persist transcripts
        transcript_sink = TranscriptSink(self.output_root)
        text_events = [e for e in collector.events if e.event_type in TEXT_EVENT_TYPES]
        logger.debug(f"Writing {len(text_events)} transcript events")
        transcript_sink.write_transcripts(text_events)

        # Persist raw WebSocket messages
        raw_sink = RawLogSink(self.output_root, filename="sut_messages.log")
        logger.debug(f"Writing {len(raw_messages)} raw WebSocket messages")
        raw_sink.append_messages(raw_messages)

        logger.info(f"Results persistence completed successfully to {self.output_root}")


__all__ = ["ResultsPersistenceService"]
