"""Base message handler abstraction.

Defines the MessageHandler protocol that all concrete handlers must implement.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolEvent


logger = logging.getLogger(__name__)


class MessageHandler(ABC):
    """Abstract base class for message handlers.

    Each handler processes a specific message type from the WebSocket stream
    and converts it into a structured ProtocolEvent.

    Handlers follow the Strategy pattern, allowing the ProtocolAdapter to
    delegate message-specific decoding without complex conditional branches.
    """

    def __init__(self, adapter: Any) -> None:
        """Initialize the message handler.

        Args:
            adapter: Protocol adapter instance for shared state (e.g., transcript buffers)
        """
        self.adapter = adapter

    @abstractmethod
    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if this handler can process the message, False otherwise
        """
        pass

    @abstractmethod
    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode the message into a ProtocolEvent.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent containing structured event data
        """
        pass


__all__ = ["MessageHandler"]