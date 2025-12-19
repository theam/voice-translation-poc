from __future__ import annotations

import logging
from typing import AsyncIterator

from .base import ProviderRequest, ProviderResponse, TranslationProvider

logger = logging.getLogger(__name__)


class VoiceLiveProvider(TranslationProvider):
    name = "voicelive"

    def __init__(self, endpoint: str | None = None, api_key: str | None = None):
        self.endpoint = endpoint
        self.api_key = api_key

    async def connect(self) -> None:
        logger.info("VoiceLiveProvider connect (stub). endpoint=%s", self.endpoint)

    async def close(self) -> None:
        logger.info("VoiceLiveProvider close (stub)")

    async def translate(self, request: ProviderRequest) -> AsyncIterator[ProviderResponse]:
        # Placeholder: in a real implementation this would stream to the provider
        logger.info(
            "VoiceLiveProvider sending request session=%s participant=%s commit=%s",
            request.session_id,
            request.participant_id,
            request.commit_id,
        )
        yield ProviderResponse(
            text="VoiceLive stub response",
            partial=False,
            session_id=request.session_id,
            participant_id=request.participant_id,
            commit_id=request.commit_id,
        )

    async def health(self) -> str:
        return "ok" if self.endpoint else "degraded"

