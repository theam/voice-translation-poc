"""Turn processors for scenario playback.

This package provides a Strategy pattern implementation for handling different
turn types during scenario execution. Each processor encapsulates the logic
for a specific turn type, making the system extensible and maintainable.

## Architecture

The turn processor system consists of:

- **Base**: `TurnProcessor` abstract base class defining the interface
- **Concrete Processors**: Implementations for specific turn types
  - `AudioTurnProcessor` - play_audio turns
  - `SilenceTurnProcessor` - silence turns
  - `HangupTurnProcessor` - hangup turns
  - `LoopbackTextTurnProcessor` - loopback_text turns
- **Factory**: `create_turn_processor()` for instantiating the right processor

## Usage

```python
from production.scenario_engine.turn_processors import create_turn_processor

# Create a processor for a turn
processor = create_turn_processor(
    turn_type="play_audio",
    ws=websocket_client,
    adapter=protocol_adapter,
    clock=clock,
    tape=tape,
    sample_rate=16000,
    channels=1
)

# Process the turn
current_time = await processor.process(turn, scenario, participants, current_time)
```

## Extending

To add a new turn type:

1. Create a new processor class inheriting from `TurnProcessor`
2. Implement the `process()` method
3. Add the processor to the factory map in `create_turn_processor()`

Example:

```python
# turn_processors/recording.py
from production.scenario_engine.turn_processors.base import TurnProcessor

class RecordingStartProcessor(TurnProcessor):
    async def process(self, turn, scenario, participants, current_time):
        current_time = await self._stream_silence_until(
            participants, current_time, turn.start_at_ms
        )
        await self.ws.send_json(
            self.adapter.build_control_message(
                "recording_start", participant_id=turn.participant
            )
        )
        return current_time

# Then add to factory map:
# "recording_start": RecordingStartProcessor
```
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from production.scenario_engine.turn_processors.audio import AudioTurnProcessor
from production.scenario_engine.turn_processors.base import TurnProcessor
from production.scenario_engine.turn_processors.hangup import HangupTurnProcessor
from production.scenario_engine.turn_processors.loopback_text import LoopbackTextTurnProcessor
from production.scenario_engine.turn_processors.silence import SilenceTurnProcessor

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter
    from production.acs_emulator.websocket_client import WebSocketClient
    from production.capture.conversation_manager import ConversationManager
    from production.capture.conversation_tape import ConversationTape
    from production.utils.time_utils import Clock


def create_turn_processor(
    turn_type: str,
    ws: WebSocketClient,
    adapter: ProtocolAdapter,
    clock: Clock,
    tape: ConversationTape,
    sample_rate: int,
    channels: int,
    conversation_manager: "ConversationManager",
) -> TurnProcessor:
    """Factory method to create the appropriate turn processor.

    This factory uses a simple mapping strategy to instantiate the correct
    processor based on turn type. Adding new turn types requires only
    updating the processor_map dictionary.

    Turns are part of the test scenario definition (YAML files) and describe
    actions to be executed during scenario playback, such as playing audio,
    introducing silence, or ending the call. Each turn has a type, timing,
    and participant information.

    Args:
        turn_type: Type of turn (play_audio, silence, hangup). Turns are
            defined in scenario YAML files and describe actions to execute
            during test playback.
        ws: WebSocket client for sending messages
        adapter: Protocol adapter for encoding messages
        clock: Clock for time acceleration and sleep
        tape: Conversation tape for recording audio
        sample_rate: Audio sample rate in Hz
        channels: Number of audio channels

    Returns:
        TurnProcessor instance for the specified turn type

    Raises:
        ValueError: If turn_type is not recognized

    Example:
        >>> processor = create_turn_processor(
        ...     turn_type="play_audio",
        ...     ws=ws_client,
        ...     adapter=proto_adapter,
        ...     clock=clock,
        ...     tape=tape,
        ...     sample_rate=16000,
        ...     channels=1
        ... )
        >>> current_time = await processor.process(turn, scenario, participants, 0)
    """
    processor_map = {
        "play_audio": AudioTurnProcessor,
        "silence": SilenceTurnProcessor,
        "hangup": HangupTurnProcessor,
        "loopback_text": LoopbackTextTurnProcessor,
    }

    processor_class = processor_map.get(turn_type)
    if processor_class is None:
        raise ValueError(
            f"Unknown turn type: {turn_type}. "
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
    "TurnProcessor",
    "AudioTurnProcessor",
    "SilenceTurnProcessor",
    "HangupTurnProcessor",
    "LoopbackTextTurnProcessor",
    "create_turn_processor",
]
