from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from .base import ProviderRequest, ProviderResponse, TranslationProvider

logger = logging.getLogger(__name__)


class MockProvider(TranslationProvider):
    name = "mock"

    async def connect(self) -> None:
        logger.info("MockProvider connected")

    async def close(self) -> None:
        logger.info("MockProvider closed")

    async def translate(self, request: ProviderRequest) -> AsyncIterator[ProviderResponse]:
        # Emit a partial then final response to simulate streaming providers
        logger.debug(
            "MockProvider received request session=%s participant=%s commit=%s bytes=%s",
            request.session_id,
            request.participant_id,
            request.commit_id,
            len(request.audio_chunks),
        )
        yield ProviderResponse(
            text="(mock partial) processing",
            partial=True,
            session_id=request.session_id,
            participant_id=request.participant_id,
            commit_id=request.commit_id,
        )
        await asyncio.sleep(0.01)
        yield ProviderResponse(
            text="(mock final) translated text",
            partial=False,
            session_id=request.session_id,
            participant_id=request.participant_id,
            commit_id=request.commit_id,
        )

    async def health(self) -> str:
        return "ok"

