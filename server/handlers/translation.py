from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from ..envelope import Envelope
from ..provider_client import ProviderClient
from ..providers.base import ProviderRequest
from ..queues import OverflowPolicy
from ..event_bus import EventBus
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


AudioKey = Tuple[str, str | None]


class TranslationDispatchHandler(Handler):
    """Consumes ACS envelopes, buffers audio, and dispatches to provider."""

    def __init__(self, settings: HandlerSettings, provider_client: ProviderClient, provider_inbound_bus: EventBus):
        super().__init__(settings)
        self._provider_client = provider_client
        self._provider_inbound_bus = provider_inbound_bus
        self._buffers: Dict[AudioKey, List[bytes]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def handle(self, envelope: Envelope) -> None:
        if envelope.type.startswith("audio"):
            await self._handle_audio(envelope)
        elif envelope.type == "control":
            logger.info("Control event received: %s", envelope.message_id)
        else:
            logger.debug("Ignoring unsupported envelope type: %s", envelope.type)

    async def _handle_audio(self, envelope: Envelope) -> None:
        key: AudioKey = (envelope.session_id, envelope.participant_id)
        chunk_b64 = envelope.payload.get("audio_b64")
        if chunk_b64:
            self._buffers[key].append(chunk_b64.encode())
        if envelope.type == "audio.commit":
            await self._flush_commit(envelope, key)

    async def _flush_commit(self, envelope: Envelope, key: AudioKey) -> None:
        async with self._lock:
            audio_chunks = b"".join(self._buffers.pop(key, []))
        request = ProviderRequest(
            session_id=envelope.session_id,
            participant_id=envelope.participant_id,
            commit_id=envelope.commit_id,
            audio_chunks=audio_chunks,
            metadata={"timestamp_utc": envelope.timestamp_utc, "message_id": envelope.message_id},
        )
        logger.info("Dispatching provider request for commit=%s bytes=%s", envelope.commit_id, len(audio_chunks))
        async for response in self._provider_client.submit(request):
            await self._provider_inbound_bus.publish(response)

