"""Message handlers for decoding WebSocket messages.

This package provides a Strategy pattern implementation for handling different
message types received from the translation service. Each handler encapsulates
the decoding logic for a specific message format, making the system extensible
and maintainable.

## Architecture

The message handler system consists of:

- **Base**: `MessageHandler` abstract base class defining the interface
- **Concrete Handlers**: Implementations for specific message types
  - `AudioDataHandler` - AudioData messages (kind="AudioData")
  - `AudioMetadataHandler` - AudioMetadata messages (kind="AudioMetadata")
  - `TranscriptHandler` - Transcript messages (type="transcript")
  - `TextDeltaHandler` - Translation text delta messages (type="translation.text_delta")
  - `LegacyAudioHandler` - Legacy audio messages (type="audio")
- **Factory**: `get_message_handlers()` for creating the handler chain

## Usage

```python
from production.acs_emulator.message_handlers import get_message_handlers

# Create handler chain
handlers = get_message_handlers(protocol_adapter)

# Decode a message by trying each handler in order
for handler in handlers:
    if handler.can_handle(message):
        event = handler.decode(message)
        break
```

## Extending

To add a new message type:

1. Create a new handler class inheriting from `MessageHandler`
2. Implement the `can_handle()` and `decode()` methods
3. Add the handler to the list in `get_message_handlers()`

Example:

```python
# message_handlers/custom.py
from production.acs_emulator.message_handlers.base import MessageHandler

class CustomMessageHandler(MessageHandler):
    def can_handle(self, message):
        return message.get("type") == "custom"

    def decode(self, message):
        return ProtocolEvent(
            event_type="custom",
            participant_id=message.get("participant_id"),
            source_language=None,
            target_language=None,
            timestamp_ms=0,
            raw=message,
        )

# Then add to get_message_handlers():
# handlers.append(CustomMessageHandler(adapter))
```

## Handler Order

Handlers are checked in order. The first handler that returns True from
`can_handle()` will process the message. The `UnknownMessageHandler` should
always be last as it accepts all messages (fallback).

Current order:
1. AudioDataHandler (kind="AudioData")
2. AudioMetadataHandler (kind="AudioMetadata")
3. TranscriptHandler (type="transcript")
4. TextDeltaHandler (type="translation.text_delta")
5. LegacyAudioHandler (type="audio")
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from production.acs_emulator.message_handlers.audio_data import AudioDataHandler
from production.acs_emulator.message_handlers.audio_metadata import AudioMetadataHandler
from production.acs_emulator.message_handlers.base import MessageHandler
from production.acs_emulator.message_handlers.legacy_audio import LegacyAudioHandler
from production.acs_emulator.message_handlers.text_delta import TextDeltaHandler
from production.acs_emulator.message_handlers.transcript import TranscriptHandler

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter


def get_message_handlers(adapter: ProtocolAdapter) -> List[MessageHandler]:
    """Create the chain of message handlers.

    Returns a list of message handlers in priority order. Handlers are checked
    sequentially until one returns True from can_handle(). The UnknownMessageHandler
    is always last to serve as a fallback.

    Args:
        adapter: Protocol adapter instance for shared state (e.g., transcript buffers)

    Returns:
        List of MessageHandler instances in priority order

    Example:
        >>> handlers = get_message_handlers(protocol_adapter)
        >>> for handler in handlers:
        ...     if handler.can_handle(message):
        ...         event = handler.decode(message)
        ...         break
    """
    return [
        AudioDataHandler(adapter),
        AudioMetadataHandler(adapter),
        TranscriptHandler(adapter),
        TextDeltaHandler(adapter),
        LegacyAudioHandler(adapter),
    ]


__all__ = [
    "MessageHandler",
    "AudioDataHandler",
    "AudioMetadataHandler",
    "TranscriptHandler",
    "TextDeltaHandler",
    "LegacyAudioHandler",
    "get_message_handlers",
]
