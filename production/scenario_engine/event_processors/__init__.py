"""Event processors for scenario playback.

This package provides a Strategy pattern implementation for handling different
event types during scenario execution. Each processor encapsulates the logic
for a specific event type, making the system extensible and maintainable.

## Architecture

The event processor system consists of:

- **Base**: `EventProcessor` abstract base class defining the interface
- **Concrete Processors**: Implementations for specific event types
  - `AudioEventProcessor` - play_audio events
  - `SilenceEventProcessor` - silence events
  - `HangupEventProcessor` - hangup events
- **Factory**: `create_event_processor()` for instantiating the right processor

## Usage

```python
from production.scenario_engine.event_processors import create_event_processor

# Create a processor for an event
processor = create_event_processor(
    event_type="play_audio",
    ws=websocket_client,
    adapter=protocol_adapter,
    clock=clock,
    tape=tape,
    sample_rate=16000,
    channels=1
)

# Process the event
current_time = await processor.process(event, scenario, participants, current_time)
```

## Extending

To add a new event type:

1. Create a new processor class inheriting from `EventProcessor`
2. Implement the `process()` method
3. Add the processor to the factory map in `create_event_processor()`

Example:

```python
# event_processors/recording.py
from production.scenario_engine.event_processors.base import EventProcessor

class RecordingStartProcessor(EventProcessor):
    async def process(self, event, scenario, participants, current_time):
        current_time = await self._stream_silence_until(
            participants, current_time, event.start_at_ms
        )
        await self.ws.send_json(
            self.adapter.build_control_message(
                "recording_start", participant_id=event.participant
            )
        )
        return current_time

# Then add to factory map:
# "recording_start": RecordingStartProcessor
```
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from production.scenario_engine.event_processors.audio import AudioEventProcessor
from production.scenario_engine.event_processors.base import EventProcessor
from production.scenario_engine.event_processors.hangup import HangupEventProcessor
from production.scenario_engine.event_processors.silence import SilenceEventProcessor

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter
    from production.acs_emulator.websocket_client import WebSocketClient
    from production.capture.conversation_manager import ConversationManager
    from production.capture.conversation_tape import ConversationTape
    from production.utils.time_utils import Clock


def create_event_processor(
    event_type: str,
    ws: WebSocketClient,
    adapter: ProtocolAdapter,
    clock: Clock,
    tape: ConversationTape,
    sample_rate: int,
    channels: int,
    conversation_manager: "ConversationManager",
) -> EventProcessor:
    """Factory method to create the appropriate event processor.

    This factory uses a simple mapping strategy to instantiate the correct
    processor based on event type. Adding new event types requires only
    updating the processor_map dictionary.

    Events are part of the test scenario definition (YAML files) and describe
    actions to be executed during scenario playback, such as playing audio,
    introducing silence, or ending the call. Each event has a type, timing,
    and participant information.

    Args:
        event_type: Type of event (play_audio, silence, hangup). Events are
            defined in scenario YAML files and describe actions to execute
            during test playback.
        ws: WebSocket client for sending messages
        adapter: Protocol adapter for encoding messages
        clock: Clock for time acceleration and sleep
        tape: Conversation tape for recording audio
        sample_rate: Audio sample rate in Hz
        channels: Number of audio channels

    Returns:
        EventProcessor instance for the specified event type

    Raises:
        ValueError: If event_type is not recognized

    Example:
        >>> processor = create_event_processor(
        ...     event_type="play_audio",
        ...     ws=ws_client,
        ...     adapter=proto_adapter,
        ...     clock=clock,
        ...     tape=tape,
        ...     sample_rate=16000,
        ...     channels=1
        ... )
        >>> current_time = await processor.process(event, scenario, participants, 0)
    """
    processor_map = {
        "play_audio": AudioEventProcessor,
        "silence": SilenceEventProcessor,
        "hangup": HangupEventProcessor,
    }

    processor_class = processor_map.get(event_type)
    if processor_class is None:
        raise ValueError(
            f"Unknown event type: {event_type}. "
            f"Supported types: {', '.join(processor_map.keys())}"
        )

    return processor_class(
        ws=ws,
        adapter=adapter,
        clock=clock,
        tape=tape,
        sample_rate=sample_rate,
        channels=channels,
        conversation_manager=conversation_manager,
    )


__all__ = [
    "EventProcessor",
    "AudioEventProcessor",
    "SilenceEventProcessor",
    "HangupEventProcessor",
    "create_event_processor",
]
