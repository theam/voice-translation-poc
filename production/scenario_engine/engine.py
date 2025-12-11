"""Runtime engine that drives scenarios against the translation service."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import wave
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Tuple

from bson import ObjectId

from production.acs_emulator.media_engine import FRAME_DURATION_MS, async_stream_silence
from production.acs_emulator.protocol_adapter import ProtocolAdapter
from production.acs_emulator.websocket_client import WebSocketClient
from production.metrics import MetricsRunner, MetricsSummary
from production.capture.collector import CollectedEvent, EventCollector
from production.capture.conversation_manager import ConversationManager
from production.capture.conversation_tape import ConversationTape
from production.capture.results_persistence_service import ResultsPersistenceService
from production.scenario_engine.event_processors import create_event_processor
from production.scenario_engine.models import Participant, Scenario
from production.utils.config import FrameworkConfig
from production.utils.time_utils import Clock

if TYPE_CHECKING:
    from production.storage.service import MetricsStorageService

logger = logging.getLogger(__name__)


class ScenarioEngine:
    def __init__(
        self,
        config: FrameworkConfig,
        storage_service: Optional[MetricsStorageService] = None,
        evaluation_run_id: Optional[ObjectId] = None
    ) -> None:
        """Initialize scenario engine.

        Args:
            config: Framework configuration
            storage_service: Optional storage service for metrics persistence
            evaluation_run_id: Optional evaluation run ID for linking test results
        """
        self.config = config
        self.clock = Clock(acceleration=config.time_acceleration)
        self.storage_service = storage_service
        self.evaluation_run_id = evaluation_run_id

    async def run(
        self,
        scenario: Scenario,
        started_at: Optional[datetime] = None
    ) -> tuple[MetricsSummary, ConversationManager]:
        # Create persistence service to manage all result storage
        persistence_service = ResultsPersistenceService(
            base_output_dir=self.config.ensure_output_dir(),
            scenario_id=scenario.id,
            evaluation_run_id=self.evaluation_run_id
        )

        collector = EventCollector()
        started_at_ms = self.clock.now_ms()
        conversation_manager = ConversationManager(
            clock=self.clock, scenario_started_at_ms=started_at_ms
        )
        raw_messages: List[dict] = []
        adapter = ProtocolAdapter(call_id=scenario.id)
        metadata, sample_rate, channels = self._build_audio_metadata(adapter, scenario)
        effective_sample_rate = sample_rate or 16000
        effective_channels = channels or 1
        tape = ConversationTape(sample_rate=effective_sample_rate)

        async with WebSocketClient(
            url=self.config.websocket_url,
            auth_key=self.config.auth_key,
            connect_timeout=self.config.connect_timeout,
            debug_wire=self.config.debug_wire,
            log_sink=persistence_service.get_websocket_sink(),
        ) as ws:
            listener = asyncio.create_task(
                self._listen(
                    ws,
                    adapter,
                    collector,
                    conversation_manager,
                    raw_messages,
                    tape,
                    started_at_ms,
                )
            )
            if metadata:
                await ws.send_json(metadata)
            await self._play_scenario(
                ws,
                adapter,
                scenario,
                tape,
                effective_sample_rate,
                effective_channels,
                conversation_manager,
            )
            await asyncio.sleep(1 / self.clock.acceleration)
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

        # Persist results using the service
        persistence_service.persist_results(collector, raw_messages, tape)

        # Create MetricsRunner with storage integration
        test_started_at = started_at or datetime.utcnow()
        runner = MetricsRunner(
            scenario.expectations,
            conversation_manager,
            storage_service=self.storage_service,
            evaluation_run_id=self.evaluation_run_id,
            test_id=scenario.id,
            test_name=scenario.description,
            started_at=test_started_at
        )

        # Run and persist metrics if storage is configured
        if self.storage_service:
            summary = await runner.run_and_persist(
                tags=scenario.tags,
                participants=list(scenario.participants.keys())
            )
        else:
            summary = runner.run()

        return summary, conversation_manager

    async def _play_scenario(
        self,
        ws: WebSocketClient,
        adapter: ProtocolAdapter,
        scenario: Scenario,
        tape: ConversationTape,
        sample_rate: int,
        channels: int,
        conversation_manager: ConversationManager,
    ) -> None:
        """Play a scenario by processing events in timeline order.

        The engine orchestrates timing by:
        1. Streaming silence to reach each event's start time
        2. Delegating event-specific logic to processors
        3. Tracking current playback position

        Processors focus purely on event execution, not timing orchestration.

        Args:
            ws: WebSocket client for sending messages
            adapter: Protocol adapter for encoding messages
            scenario: The scenario to play
            tape: Conversation tape for recording audio
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
        """
        timeline = sorted(scenario.events, key=lambda event: event.start_at_ms)
        current_time = 0
        participants = list(scenario.participants.values())

        # Process each event with orchestrated timing
        for event in timeline:
            logger.info(
                f"Processing event '{event.id}': start_at={event.start_at_ms}ms, "
                f"current_time={current_time}ms, silence_needed={event.start_at_ms - current_time}ms"
            )
            # Orchestration: Stream silence until event start time
            current_time = await self._stream_silence_until(
                ws, adapter, participants, current_time, event.start_at_ms, sample_rate, channels, tape
            )

            conversation_manager.start_turn(event.id, {"type": event.type, "start_at_ms": event.start_at_ms})

            # Execution: Process the event
            processor = create_event_processor(
                event_type=event.type,
                ws=ws,
                adapter=adapter,
                clock=self.clock,
                tape=tape,
                sample_rate=sample_rate,
                channels=channels,
                conversation_manager=conversation_manager,
            )
            current_time = await processor.process(event, scenario, participants, current_time)

            logger.debug(f"After processing event '{event.id}', current_time={current_time}ms")

        # Stream trailing silence to allow translations to arrive before teardown
        tail_target = current_time + self.config.tail_silence_ms
        current_time = await self._stream_silence_until(
            ws, adapter, participants, current_time, tail_target, sample_rate, channels, tape
        )

    async def _stream_silence_until(
        self,
        ws: WebSocketClient,
        adapter: ProtocolAdapter,
        participants: List[Participant],
        current_time: int,
        target_ms: int,
        sample_rate: int,
        channels: int,
        tape: ConversationTape,
    ) -> int:
        """Stream silence frames from current_time to target_ms.

        Uses media_engine for silence generation, maintaining separation of
        concerns between orchestration (ScenarioEngine) and media operations
        (media_engine).

        Args:
            ws: WebSocket client for sending messages
            adapter: Protocol adapter for encoding messages
            participants: List of participants to stream silence for
            current_time: Current playback position in milliseconds
            target_ms: Target timestamp to reach
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
            tape: Conversation tape for recording

        Returns:
            Updated current time position
        """
        if target_ms <= current_time:
            return current_time

        duration_ms = target_ms - current_time

        async for frame in async_stream_silence(
            duration_ms=duration_ms,
            start_time_ms=current_time,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=2,  # 16-bit PCM
            frame_duration_ms=FRAME_DURATION_MS
        ):
            for participant in participants:
                payload = adapter.build_audio_message(
                    participant_id=participant.name,
                    pcm_bytes=frame.data,
                    timestamp_ms=frame.timestamp_ms,
                    silent=frame.is_silence,
                )
                await ws.send_json(payload)
                tape.add_pcm(frame.timestamp_ms, frame.data)

            await self.clock.sleep(FRAME_DURATION_MS)

        return target_ms

    async def _listen(
        self,
        ws: WebSocketClient,
        adapter: ProtocolAdapter,
        collector: EventCollector,
        conversation_manager: ConversationManager,
        raw_messages: List[dict],
        tape: ConversationTape,
        started_at_ms: int,
    ) -> None:
        async for message in ws.iter_messages():
            raw_messages.append(message)
            protocol_event = adapter.decode_inbound(message)
            if protocol_event is None:
                continue

            arrival_ms = self.clock.now_ms() - started_at_ms
            raw_ts = protocol_event.timestamp_ms
            # If the SUT sends absolute timestamps (e.g., UNIX epoch ms),
            # normalize them to the scenario start time to avoid multi-hour
            # gaps of silence in the mixed call tape. Otherwise respect the
            # provided relative timestamp or fall back to arrival time.
            if raw_ts is not None and raw_ts > 1_000_000_000:
                timestamp_ms = max(0, raw_ts - started_at_ms)
            else:
                timestamp_ms = raw_ts if raw_ts is not None else arrival_ms
            collected = CollectedEvent(
                event_type=protocol_event.event_type,
                timestamp_ms=timestamp_ms,
                participant_id=protocol_event.participant_id,
                source_language=protocol_event.source_language,
                target_language=protocol_event.target_language,
                text=protocol_event.text,
                audio_payload=protocol_event.audio_payload,
                raw=protocol_event.raw,
            )
            collector.add(collected)
            conversation_manager.register_incoming(collected)
            if protocol_event.event_type == "translated_audio" and protocol_event.audio_payload:
                tape.add_pcm(arrival_ms, protocol_event.audio_payload)

    def _build_audio_metadata(
        self, adapter: ProtocolAdapter, scenario: Scenario
    ) -> Tuple[Optional[dict], Optional[int], Optional[int]]:
        """Construct the ACS AudioMetadata payload based on the first audio asset.

        ACS emits metadata before streaming audio frames. The emulator mirrors this
        by inspecting the first ``play_audio`` event to determine sample rate,
        channel count, and expected frame size.

        Returns:
            Tuple of (metadata_payload, sample_rate, channels)
        """

        for event in sorted(scenario.events, key=lambda evt: evt.start_at_ms):
            if event.type != "play_audio":
                continue
            participant = scenario.participants[event.participant]
            audio_path = participant.audio_files[event.audio_file]  # type: ignore[index]
            with wave.open(str(audio_path), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()

            if sample_width != 2:
                raise ValueError(
                    f"Unsupported audio format for ACS emulation: expected 16-bit PCM, got sample width {sample_width}"
                )

            frame_bytes = int(sample_rate * (FRAME_DURATION_MS / 1000.0) * channels * sample_width)
            logger.debug(
                "Sending ACS AudioMetadata with sample_rate=%s channels=%s frame_bytes=%s", sample_rate, channels, frame_bytes
            )
            payload = adapter.build_audio_metadata(sample_rate=sample_rate, channels=channels, frame_bytes=frame_bytes)
            return payload, sample_rate, channels

        logger.warning("Scenario contains no play_audio events; skipping AudioMetadata emission")
        return None, None, None
