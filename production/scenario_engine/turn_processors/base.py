"""Base turn processor abstraction.

Defines the TurnProcessor protocol that all concrete processors must implement.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter
    from production.acs_emulator.websocket_client import WebSocketClient
    from production.capture.conversation_manager import ConversationManager
    from production.scenario_engine.models import ScenarioTurn, Participant, Scenario
    from production.utils.time_utils import Clock


logger = logging.getLogger(__name__)


class TurnProcessor(ABC):
    """Abstract base class for turn processors.

    Each processor handles a specific turn type and encapsulates the logic
    for executing turn-specific operations (audio playback, control messages, etc.).

    Processors follow the Strategy pattern, allowing the ScenarioEngine to
    delegate turn-specific logic without complex conditional branches.

    Timing orchestration (silence filling) is handled by the ScenarioEngine,
    not by processors. Processors focus purely on turn execution.
    """

    def __init__(
        self,
        ws: WebSocketClient,
        adapter: ProtocolAdapter,
        clock: Clock,
        sample_rate: int,
        channels: int,
        conversation_manager: "ConversationManager",
    ) -> None:
        """Initialize the turn processor.

        Args:
            ws: WebSocket client for sending messages
            adapter: Protocol adapter for encoding messages
            clock: Clock for time acceleration and sleep
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
        """
        self.ws = ws
        self.adapter = adapter
        self.clock = clock
        self.sample_rate = sample_rate
        self.channels = channels
        self.conversation_manager = conversation_manager

    @abstractmethod
    async def process(
        self,
        turn: ScenarioTurn,
        scenario: Scenario,
        participants: list[Participant],
        current_scn_ms: int,
    ) -> int:
        """Process a turn and return the updated current time.

        The processor should execute turn-specific logic (audio playback,
        control messages, etc.) and return the new current time.

        Timing orchestration (silence filling to reach turn.start_at_ms) is
        handled by the ScenarioEngine before calling this method.

        Args:
            turn: The turn to process (current_scn_ms already at turn.start_at_ms)
            scenario: The full scenario context
            participants: List of all participants
            current_scn_ms: Current playback position in milliseconds (== turn.start_at_ms)

        Returns:
            Updated current time position in milliseconds
        """
        pass


__all__ = ["TurnProcessor"]
