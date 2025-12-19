from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .providers.base import ProviderRequest, TranslationProvider
from .providers.factory import create_provider

logger = logging.getLogger(__name__)


class ProviderClient:
    def __init__(self, provider: TranslationProvider, *, max_concurrency: int, request_timeout_ms: int):
        self.provider = provider
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._request_timeout = request_timeout_ms / 1000

    @classmethod
    def from_config(cls, name: str, *, provider_options: dict, max_concurrency: int, request_timeout_ms: int) -> "ProviderClient":
        provider = create_provider(name, **provider_options)
        return cls(provider, max_concurrency=max_concurrency, request_timeout_ms=request_timeout_ms)

    async def connect(self) -> None:
        await self.provider.connect()

    async def close(self) -> None:
        await self.provider.close()

    async def submit(self, request: ProviderRequest):
        await self._semaphore.acquire()
        try:
            iterator = self.provider.translate(request)
            while True:
                try:
                    response = await asyncio.wait_for(iterator.__anext__(), timeout=self._request_timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        "Provider request timeout for session=%s participant=%s", request.session_id, request.participant_id
                    )
                    break
                else:
                    yield response
        except asyncio.TimeoutError:
            logger.warning("Provider request timeout for session=%s participant=%s", request.session_id, request.participant_id)
        finally:
            self._semaphore.release()
