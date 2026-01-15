from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent, OutboundAudioDoneEvent
from ...session.input_state import InputState
from ..base import Handler

logger = logging.getLogger(__name__)


class OutboundGateMode(str, Enum):
    """Gate modes for provider audio based on input state."""
    PLAY_THROUGH = "play_through"          # Always send audio
    PAUSE_AND_BUFFER = "pause_and_buffer"  # Pause handler, buffer in bus queue
    PAUSE_AND_DROP = "pause_and_drop"      # Pause handler, drop buffered audio

    def is_play_through(self) -> bool:
        """Check if this mode is PLAY_THROUGH."""
        return self == OutboundGateMode.PLAY_THROUGH

    def is_pause_and_buffer(self) -> bool:
        """Check if this mode is PAUSE_AND_BUFFER."""
        return self == OutboundGateMode.PAUSE_AND_BUFFER

    def is_pause_and_drop(self) -> bool:
        """Check if this mode is PAUSE_AND_DROP."""
        return self == OutboundGateMode.PAUSE_AND_DROP

    @classmethod
    def from_value(cls, value: Optional[str]) -> "OutboundGateMode":
        """Parse gate mode from config string."""
        if not value:
            return cls.PLAY_THROUGH
        normalized = str(value).strip().lower()
        for mode in cls:
            if mode.value == normalized:
                return mode
        logger.warning("Unknown gate mode '%s', defaulting to PLAY_THROUGH", value)
        return cls.PLAY_THROUGH


class ProviderAudioGateHandler(Handler):
    """
    Gates provider audio based on input state (barge-in).

    Controls the downstream handler (OutboundPlayoutHandler) by pausing/resuming
    it via the gated_audio_bus. This leverages the bus's built-in queuing.
    """

    def __init__(
        self,
        gated_bus: EventBus,
        input_state: InputState,
        downstream_handler_name: str,      # Name of handler to pause/resume
        playout_store,                      # Reference to PlayoutStore for cancellation
        playout_engine,                     # Reference to PacedPlayoutEngine
        gate_mode: OutboundGateMode,
        session_id: str,
    ):
        self._gated_bus = gated_bus
        self._input_state = input_state
        self._downstream_handler_name = downstream_handler_name
        self._playout_store = playout_store
        self._playout_engine = playout_engine
        self._gate_mode = gate_mode
        self._session_id = session_id

        # Register as InputState listener
        self._input_state.add_listener(self._on_input_state_changed)

        logger.info(
            "ProviderAudioGateHandler initialized session=%s mode=%s",
            self._session_id,
            self._gate_mode.value
        )

    def can_handle(self, event: OutboundAudioBytesEvent | OutboundAudioDoneEvent) -> bool:
        return isinstance(event, (OutboundAudioBytesEvent, OutboundAudioDoneEvent))

    async def handle(self, event: OutboundAudioBytesEvent | OutboundAudioDoneEvent) -> None:
        """
        Forward audio events to gated_bus. Gating is controlled by pausing/resuming
        the downstream handler, not by blocking here.
        """
        await self._gated_bus.publish(event)

    async def _on_input_state_changed(self, input_state: InputState) -> None:
        """React to input state transitions for barge-in control."""

        if self._gate_mode.is_play_through():
            return  # No gating

        # User started speaking → PAUSE and DRAIN
        if input_state.status.is_speaking():
            await self._on_speaking_started()

        # User stopped speaking → RESUME (and optionally DROP)
        elif input_state.status.is_silence():
            await self._on_silence_resumed()

    async def _on_speaking_started(self) -> None:
        """Handle barge-in: user started speaking."""
        try:
            # 1. Pause the downstream handler (stops consuming from gated_audio_bus)
            await self._gated_bus.pause(self._downstream_handler_name)
            logger.info(
                "PAUSE(%s): downstream handler paused session=%s mode=%s",
                self._gate_mode.value,
                self._session_id,
                self._gate_mode.value
            )

            if self._gate_mode.is_pause_and_drop():
                await self._clear_all_playout_streams()
            elif self._gate_mode.is_pause_and_buffer():
                await self._pause_all_playout_streams()

        except KeyError as e:
            logger.error(
                "Failed to pause handler session=%s: %s",
                self._session_id,
                e
            )

    async def _on_silence_resumed(self) -> None:
        """Handle resume: user stopped speaking."""
        try:
            # For PAUSE_AND_DROP: clear the queue before resuming
            if self._gate_mode.is_pause_and_drop():
                cleared = await self._gated_bus.clear(self._downstream_handler_name)
                logger.info(
                    "DROP(%s): cleared %d queued events session=%s",
                    self._gate_mode.value,
                    cleared,
                    self._session_id
                )

            # Resume the downstream handler (starts consuming from bus queue)
            await self._gated_bus.resume(self._downstream_handler_name)
            await self._resume_all_playout_streams()
            logger.info(
                "RESUME(%s): downstream handler and playout resumed session=%s",
                self._gate_mode.value,
                self._session_id
            )
        except KeyError as e:
            logger.error(
                "Failed to resume handler session=%s: %s",
                self._session_id,
                e
            )

    async def _pause_all_playout_streams(self) -> None:
        """Pause all active playout streams."""
        streams = list(self._playout_store.keys())
        for stream_key in streams:
            stream = self._playout_store.get(stream_key)
            if stream:
                await self._playout_engine.pause(stream)  # real pause, not done=True
                # DO NOT remove from store

        logger.info(
            "Paused %d playout streams session=%s",
            len(streams),
            self._session_id
        )

    async def _clear_all_playout_streams(self) -> None:
        """Drop all active playout streams and clear their buffers."""
        streams = list(self._playout_store.keys())
        for stream_key in streams:
            stream = self._playout_store.get(stream_key)
            if stream:
                await self._playout_engine.pause(stream)
                await self._playout_engine.clear(stream)

        logger.info(
            "Dropped %d playout streams session=%s",
            len(streams),
            self._session_id
        )

    async def _resume_all_playout_streams(self) -> None:
        """Resume all paused playout streams."""
        streams = list(self._playout_store.keys())
        for stream_key in streams:
            stream = self._playout_store.get(stream_key)
            if stream:
                await self._playout_engine.resume(stream)

    async def shutdown(self) -> None:
        """Cleanup on session teardown."""
        # Ensure handler is resumed on shutdown
        try:
            await self._gated_bus.resume(self._downstream_handler_name)
        except Exception:
            pass  # Best effort


__all__ = ["ProviderAudioGateHandler", "OutboundGateMode"]
