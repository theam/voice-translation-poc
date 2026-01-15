from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from ....audio import AudioFormat, StreamingPcmResampler


@dataclass
class PlayoutStream:
    key: str
    buffer: bytearray
    frame_bytes: int
    fmt: AudioFormat
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    paused: bool = False
    shutdown: bool = False
    task: Optional[asyncio.Task] = None
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    resampler: Optional[StreamingPcmResampler] = None

    def has_full_frame(self) -> bool:
        return self.frame_bytes > 0 and len(self.buffer) >= self.frame_bytes


class PlayoutStore:
    """Holds active playout streams."""

    def __init__(self) -> None:
        self._streams: Dict[str, PlayoutStream] = {}

    def get_or_create(self, key: str, target_format: AudioFormat, frame_bytes: int) -> PlayoutStream:
        if key not in self._streams:
            self._streams[key] = PlayoutStream(
                key=key,
                buffer=bytearray(),
                frame_bytes=frame_bytes,
                fmt=target_format
            )
        return self._streams[key]

    def get(self, key: str) -> Optional[PlayoutStream]:
        return self._streams.get(key)

    def remove(self, key: str) -> None:
        self._streams.pop(key, None)

    def keys(self) -> Iterable[str]:
        return self._streams.keys()
