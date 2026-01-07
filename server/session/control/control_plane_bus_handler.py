from __future__ import annotations

import logging

from ...gateways.base import Handler, HandlerSettings
from ...models.gateway_input_event import GatewayInputEvent
from ...models.provider_events import ProviderInputEvent
from ...models.provider_events import ProviderOutputEvent
from .session_control_plane import SessionControlPlane

logger = logging.getLogger(__name__)


class ControlPlaneBusHandler(Handler):
    """EventBus handler that forwards envelopes to the session control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        control_plane: SessionControlPlane,
        source: str,
    ) -> None:
        super().__init__(settings)
        self._control_plane = control_plane
        self._source = source

    async def handle(self, envelope: object) -> None:  # type: ignore[override]
        if isinstance(envelope, GatewayInputEvent):
            await self._control_plane.process_gateway(envelope)
            return

        if isinstance(envelope, ProviderOutputEvent):
            await self._control_plane.process_provider(envelope)
            return

        if isinstance(envelope, ProviderInputEvent):
            await self._control_plane.process_provider_input(envelope)
            return

        if isinstance(envelope, dict):
            await self._control_plane.process_outbound_payload(envelope)
            return

        logger.debug(
            "control_plane_unknown_envelope session=%s source=%s type=%s",
            self._control_plane.session_id,
            self._source,
            type(envelope),
        )


__all__ = ["ControlPlaneBusHandler"]
