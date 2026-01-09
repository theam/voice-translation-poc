from __future__ import annotations

import logging

from ...models.gateway_input_event import GatewayInputEvent

logger = logging.getLogger(__name__)


class TestSettingsHandler:
    """Handles control.test.settings messages from ACS."""

    def __init__(self, translation_settings: dict, session_metadata: dict):
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata

    def can_handle(self, event: GatewayInputEvent) -> bool:
        payload = event.payload or {}
        if not isinstance(payload, dict):
            return False
        return payload.get("type") == "control.test.settings"

    async def handle(self, event: GatewayInputEvent) -> None:
        """Handle control envelope."""
        logger.info("Control event received: %s", event.event_id)

        self._apply_settings(event)

    def _apply_settings(self, event: GatewayInputEvent) -> None:
        """Store translation settings for the session."""
        settings = event.payload.get("settings") if isinstance(event.payload, dict) else None
        if not isinstance(settings, dict):
            logger.debug("Ignoring control.test.settings without settings dict: %s", event.payload)
            return

        self.translation_settings.update(settings)
        metadata_settings = self.session_metadata.setdefault("translation_settings", {})
        if isinstance(metadata_settings, dict):
            metadata_settings.update(settings)
        logger.info("Applied translation settings: %s", settings)
