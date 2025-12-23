from __future__ import annotations

import logging

from ...models.gateway_input_event import GatewayInputEvent

logger = logging.getLogger(__name__)


class TestSettingsHandler:
    """Handles control.test.settings messages from ACS."""

    def __init__(self, translation_settings: dict, session_metadata: dict):
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata

    async def handle(self, envelope: GatewayInputEvent) -> None:
        """Handle control envelope."""
        logger.info("Control event received: %s", envelope.event_id)

        if envelope.event_type == "control.test.settings":
            self._apply_settings(envelope)

    def _apply_settings(self, envelope: GatewayInputEvent) -> None:
        """Store translation settings for the session."""
        settings = envelope.payload.get("settings") if isinstance(envelope.payload, dict) else None
        if not isinstance(settings, dict):
            logger.debug("Ignoring control.test.settings without settings dict: %s", envelope.payload)
            return

        self.translation_settings.update(settings)
        metadata_settings = self.session_metadata.setdefault("translation_settings", {})
        if isinstance(metadata_settings, dict):
            metadata_settings.update(settings)
        logger.info("Applied translation settings: %s", settings)
