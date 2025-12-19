from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..adapters.egress import ACSEgressAdapter
from ..providers.base import ProviderResponse
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class ProviderResultHandler(Handler):
    def __init__(self, settings: HandlerSettings, egress_adapter: Optional[ACSEgressAdapter] = None):
        super().__init__(settings)
        self.egress_adapter = egress_adapter

    async def handle(self, response: ProviderResponse) -> None:
        logger.info(
            "Provider result partial=%s session=%s participant=%s commit=%s text=%s",
            response.partial,
            response.session_id,
            response.participant_id,
            response.commit_id,
            response.text,
        )
        if self.egress_adapter:
            payload = self._to_acs_payload(response)
            await self.egress_adapter.send(payload)

    def _to_acs_payload(self, response: ProviderResponse) -> Dict[str, Any]:
        return {
            "type": "translation.result",
            "partial": response.partial,
            "session_id": response.session_id,
            "participant_id": response.participant_id,
            "commit_id": response.commit_id,
            "text": response.text,
        }

