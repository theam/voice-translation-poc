from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from ...core.event_bus import EventBus
from ..capabilities import ProviderAudioCapabilities, get_provider_capabilities
from .inbound_handlers import (
    AudioDeltaHandler,
    AudioDoneHandler,
    AudioTranscriptDeltaHandler,
    AudioTranscriptDoneHandler,
    LoggingOnlyHandler,
    ResponseCompletedHandler,
    ResponseErrorHandler,
    ResponseOutputTextDeltaHandler,
    ResponseOutputTextDoneHandler,
    VoiceLiveMessageHandler,
)


class VoiceLiveInboundHandler:
    """Dispatch VoiceLive messages to dedicated handlers and publish translations."""

    def __init__(
        self,
        inbound_bus: EventBus,
        session_metadata: Dict[str, Any],
        provider: str = "voice_live",
        capabilities: ProviderAudioCapabilities | None = None,
    ):
        self.inbound_bus = inbound_bus
        self.text_buffers: Dict[str, List[str]] = defaultdict(list)
        self.transcript_buffers: Dict[str, List[str]] = defaultdict(list)
        self.audio_seq_counters: Dict[str, int] = defaultdict(int)
        self.capabilities = capabilities or get_provider_capabilities(provider)
        audio_format = self._resolve_default_format()
        self._handlers: List[VoiceLiveMessageHandler] = [
            ResponseOutputTextDeltaHandler(inbound_bus, self.text_buffers),
            ResponseOutputTextDoneHandler(inbound_bus, self.text_buffers),
            ResponseCompletedHandler(inbound_bus, self.text_buffers, self.transcript_buffers),
            AudioTranscriptDeltaHandler(inbound_bus, self.transcript_buffers),
            AudioTranscriptDoneHandler(inbound_bus, self.transcript_buffers),
            AudioDeltaHandler(inbound_bus, self.audio_seq_counters, audio_format),
            AudioDoneHandler(inbound_bus, self.audio_seq_counters),
            ResponseErrorHandler(),
            LoggingOnlyHandler(),  # Default catch-all handler for unsupported message types
        ]
        self.provider = provider

    async def handle(self, message: Dict[str, Any]) -> None:
        """Dispatch message to appropriate handler."""
        for handler in self._handlers:
            if handler.can_handle(message):
                await handler.handle(message)
                return

    def _resolve_default_format(self) -> Dict[str, Any]:
        """Derive default provider output format from capabilities."""
        fmt = self.capabilities.provider_output_format
        return {"encoding": fmt.sample_format, "sample_rate_hz": fmt.sample_rate_hz, "channels": fmt.channels}
