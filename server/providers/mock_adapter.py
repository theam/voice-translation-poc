"""Mock translation adapter for testing without external service calls."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..core.event_bus import EventBus
from ..models.provider_events import ProviderInputEvent, ProviderOutputEvent

logger = logging.getLogger(__name__)


class MockAdapter:
    """
    Mock translation adapter for testing.

    Simulates translation by:
    - Consuming AudioRequest from outbound_bus
    - Generating fake partial and final translations
    - Publishing ProviderOutputEvent to inbound_bus

    No external service calls are made.
    """

    def __init__(
        self,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        *,
        delay_ms: int = 50,
    ):
        """
        Initialize Mock adapter.

        Args:
            outbound_bus: Bus to consume AudioRequest messages from
            inbound_bus: Bus to publish ProviderOutputEvent messages to
            delay_ms: Simulated processing delay in milliseconds
        """
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.delay_ms = delay_ms

        self._egress_task: Optional[asyncio.Task] = None
        self._closed = False

    async def start(self) -> None:
        """Start the mock adapter."""
        if self._closed:
            raise RuntimeError("Cannot start closed adapter")

        # Start egress loop (consumes AudioRequest, generates mock responses)
        self._egress_task = asyncio.create_task(
            self._egress_loop(),
            name="mock-egress-loop"
        )
        logger.info("Mock adapter started")

    async def _egress_loop(self) -> None:
        """
        Egress loop: consume AudioRequest and generate mock translations.
        """
        try:
            logger.info("Mock adapter egress loop starting")

            # Register handler on outbound bus
            from ..core.event_bus import HandlerConfig
            from ..core.queues import OverflowPolicy

            await self.outbound_bus.register_handler(
                HandlerConfig(
                    name="mock_egress",
                    queue_max=1000,
                    overflow_policy=OverflowPolicy.DROP_OLDEST,
                    concurrency=1,
                ),
                self._process_audio,
            )

            logger.info("Mock adapter handler registered")

        except Exception as e:
            logger.exception("Mock adapter egress loop failed: %s", e)

    async def _process_audio(self, request: ProviderInputEvent) -> None:
        """
        Process audio request and generate mock translation responses.
        Simulates partial and final translation results.
        """
        try:
            logger.info(
                "Mock adapter processing audio: commit=%s session=%s bytes=%s",
                request.commit_id,
                request.session_id,
                len(request.b64_audio_string)
            )

            # Simulate processing delay
            await asyncio.sleep(self.delay_ms / 1000 / 2)

            # Generate partial translation
            partial_response = ProviderOutputEvent(
                commit_id=request.commit_id,
                session_id=request.session_id,
                participant_id=request.participant_id,
                event_type="transcript.delta",
                payload={"text": f"[mock partial] processing commit {request.commit_id[:8]}...", "final": False},
                provider="mock",
                stream_id=request.commit_id,
            )
            await self.inbound_bus.publish(partial_response)
            logger.debug("Published mock partial translation: commit=%s", request.commit_id)

            # Simulate more processing
            await asyncio.sleep(self.delay_ms / 1000 / 2)

            # Generate final translation
            final_response = ProviderOutputEvent(
                commit_id=request.commit_id,
                session_id=request.session_id,
                participant_id=request.participant_id,
                event_type="transcript.done",
                payload={
                    "text": f"[mock final] translated audio for commit {request.commit_id[:8]}",
                    "final": True,
                },
                provider="mock",
                stream_id=request.commit_id,
            )
            await self.inbound_bus.publish(final_response)
            logger.info("Published mock final translation: commit=%s", request.commit_id)

        except Exception as e:
            logger.exception(
                "Failed to process mock translation: commit=%s error=%s",
                request.commit_id,
                e
            )

    async def close(self) -> None:
        """Close mock adapter."""
        self._closed = True

        if self._egress_task and not self._egress_task.done():
            self._egress_task.cancel()
            try:
                await self._egress_task
            except asyncio.CancelledError:
                pass

        logger.info("Mock adapter closed")

    async def health(self) -> str:
        """Check adapter health status."""
        return "ok" if not self._closed else "degraded"
