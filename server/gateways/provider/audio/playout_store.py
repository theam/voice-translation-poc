from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from ....audio import AudioFormat


@dataclass
class PlayoutState:
    buffer: bytearray
    frame_bytes: int
    fmt: AudioFormat
    done: bool = False
    task: Optional[asyncio.Task] = None
    data_ready: asyncio.Event = field(default_factory=asyncio.Event)


class PlayoutStore:
    """Holds per-stream playout state."""

    def __init__(self) -> None:
        self._states: Dict[str, PlayoutState] = {}

    def get_or_create(self, key: str, target_format: AudioFormat, frame_bytes: int) -> PlayoutState:
        if key not in self._states:
            self._states[key] = PlayoutState(buffer=bytearray(), frame_bytes=frame_bytes, fmt=target_format)
        return self._states[key]

    def get(self, key: str) -> Optional[PlayoutState]:
        return self._states.get(key)

    def remove(self, key: str) -> None:
        self._states.pop(key, None)

    def keys(self) -> Iterable[str]:
        return self._states.keys()
