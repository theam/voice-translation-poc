from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class ActivePlayback:
    """Tracks an active audio playback stream heading to ACS."""

    buffer_key: str
    session_id: str
    participant_id: Optional[str]
    commit_id: Optional[str]
    stream_id: Optional[str]
    provider: str


class BargeInManager:
    """
    Coordinates barge-in across the session.

    - Tracks active playback streams (identified by buffer_key)
    - Marks streams as muted when a participant speaks (barge-in)
    - Signals handlers to drop further audio for muted streams
    """

    def __init__(self):
        self._active: Dict[str, ActivePlayback] = {}
        self._muted: set[str] = set()
        self._lock = asyncio.Lock()
        self._clear_buffer: Optional[Callable[[str], None]] = None

    def register_buffer_clearer(self, clear_fn: Callable[[str], None]) -> None:
        """Inject callback to clear pending audio frames for a buffer key."""
        self._clear_buffer = clear_fn

    async def register_playback(
        self,
        *,
        buffer_key: str,
        session_id: str,
        participant_id: Optional[str],
        commit_id: Optional[str],
        stream_id: Optional[str],
        provider: str,
    ) -> None:
        """Record (or refresh) the active playback stream for a buffer key."""
        async with self._lock:
            self._active[buffer_key] = ActivePlayback(
                buffer_key=buffer_key,
                session_id=session_id,
                participant_id=participant_id,
                commit_id=commit_id,
                stream_id=stream_id,
                provider=provider,
            )

    async def clear_playback(self, buffer_key: str) -> None:
        """Remove tracking for a playback stream."""
        async with self._lock:
            self._active.pop(buffer_key, None)
            self._muted.discard(buffer_key)

    async def stop_for_barge_in(self, session_id: str) -> List[ActivePlayback]:
        """
        Mark active streams in this session as muted and return them so callers
        can emit stop controls to ACS.
        """
        clear_after: List[str]
        async with self._lock:
            affected = [
                stream
                for key, stream in self._active.items()
                if stream.session_id == session_id and key not in self._muted
            ]
            clear_after = [stream.buffer_key for stream in affected]
            for stream in affected:
                self._muted.add(stream.buffer_key)
        for buffer_key in clear_after:
            self.clear_buffer(buffer_key)
        return affected

    def clear_buffer(self, buffer_key: str) -> None:
        """Clear buffered audio for a stream if a callback is registered."""
        if self._clear_buffer:
            self._clear_buffer(buffer_key)

    async def is_muted(self, buffer_key: str) -> bool:
        """True if further audio for this buffer_key should be dropped."""
        async with self._lock:
            return buffer_key in self._muted
