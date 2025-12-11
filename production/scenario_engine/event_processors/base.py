"""Base event processor abstraction.

Defines the EventProcessor protocol that all concrete processors must implement.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter
    from production.acs_emulator.websocket_client import WebSocketClient
    from production.capture.conversation_manager import ConversationManager
    from production.capture.conversation_tape import ConversationTape
    from production.scenario_engine.models import Event, Participant, Scenario
    from production.utils.time_utils import Clock


logger = logging.getLogger(__name__)


class EventProcessor(ABC):
    """Abstract base class for event processors.

    Each processor handles a specific event type and encapsulates the logic
    for executing event-specific operations (audio playback, control messages, etc.).

    Processors follow the Strategy pattern, allowing the ScenarioEngine to
    delegate event-specific logic without complex conditional branches.

    Timing orchestration (silence filling) is handled by the ScenarioEngine,
    not by processors. Processors focus purely on event execution.
    """

    def __init__(
        self,
        ws: WebSocketClient,
        adapter: ProtocolAdapter,
        clock: Clock,
        tape: ConversationTape,
        sample_rate: int,
        channels: int,
        conversation_manager: "ConversationManager",
    ) -> None:
        """Initialize the event processor.

        Args:
            ws: WebSocket client for sending messages
            adapter: Protocol adapter for encoding messages
            clock: Clock for time acceleration and sleep
            tape: Conversation tape for recording audio
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
        """
        self.ws = ws
        self.adapter = adapter
        self.clock = clock
        self.tape = tape
        self.sample_rate = sample_rate
        self.channels = channels
        self.conversation_manager = conversation_manager

    @abstractmethod
    async def process(
        self,
        event: Event,
        scenario: Scenario,
        participants: list[Participant],
        current_time: int,
    ) -> int:
        """Process an event and return the updated current time.

        The processor should execute event-specific logic (audio playback,
        control messages, etc.) and return the new current time.

        Timing orchestration (silence filling to reach event.start_at_ms) is
        handled by the ScenarioEngine before calling this method.

        Args:
            event: The event to process (current_time already at event.start_at_ms)
            scenario: The full scenario context
            participants: List of all participants
            current_time: Current playback position in milliseconds (== event.start_at_ms)

        Returns:
            Updated current time position in milliseconds
        """
        pass


__all__ = ["EventProcessor"]
