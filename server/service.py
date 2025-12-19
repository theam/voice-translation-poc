from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .adapters.egress import ACSEgressAdapter
from .adapters.ingress import ACSIngressAdapter
from .config import Config, DEFAULT_CONFIG
from .envelope import Envelope
from .event_bus import EventBus, HandlerConfig
from .handlers.audit import AuditHandler
from .handlers.base import HandlerSettings
from .handlers.provider_result import ProviderResultHandler
from .handlers.translation import TranslationDispatchHandler
from .payload_capture import PayloadCapture
from .provider_client import ProviderClient
from .queues import OverflowPolicy

logger = logging.getLogger(__name__)


class ServiceApp:
    def __init__(self, config: Config):
        self.config = config
        self.loop = asyncio.get_event_loop()
        self.acs_bus = EventBus("acs_inbound_bus")
        self.provider_bus = EventBus("provider_inbound_bus")
        self.payload_capture: Optional[PayloadCapture] = None

        if config.system.payload_capture.enabled:
            self.payload_capture = PayloadCapture(
                output_dir=config.system.payload_capture.output_dir,
                mode=config.system.payload_capture.mode,
            )

        provider_options = {
            "endpoint": config.providers.voicelive.endpoint,
            "api_key": config.providers.voicelive.api_key,
            "key": config.providers.live_interpreter.key,
        }
        self.provider_client = ProviderClient.from_config(
            config.dispatch.provider,
            provider_options=provider_options,
            max_concurrency=config.dispatch.max_concurrency,
            request_timeout_ms=config.dispatch.request_timeout_ms,
        )

        self.ingress_adapter = ACSIngressAdapter(config.ingress.url, config.ingress.reconnect)
        self.egress_adapter: Optional[ACSEgressAdapter] = None
        if config.egress.destinations:
            dest = config.egress.destinations[0]
            self.egress_adapter = ACSEgressAdapter(dest.url)

    async def start(self) -> None:
        await self.provider_client.connect()
        if self.egress_adapter:
            await self.egress_adapter.connect()

        await self._register_handlers()

        await asyncio.gather(self._run_ingress(), return_exceptions=False)

    async def _register_handlers(self) -> None:
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)
        await self.acs_bus.register_handler(
            HandlerConfig(
                name="audit", queue_max=500, overflow_policy=overflow_policy, concurrency=1
            ),
            AuditHandler(
                HandlerSettings(name="audit", queue_max=500, overflow_policy=str(overflow_policy)),
                payload_capture=self.payload_capture,
            ),
        )

        await self.acs_bus.register_handler(
            HandlerConfig(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1,
            ),
            TranslationDispatchHandler(
                HandlerSettings(
                    name="translation",
                    queue_max=self.config.buffering.ingress_queue_max,
                    overflow_policy=str(self.config.buffering.overflow_policy),
                ),
                provider_client=self.provider_client,
                provider_inbound_bus=self.provider_bus,
            ),
        )

        await self.provider_bus.register_handler(
            HandlerConfig(
                name="provider_result",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1,
            ),
            ProviderResultHandler(
                HandlerSettings(
                    name="provider_result",
                    queue_max=self.config.buffering.egress_queue_max,
                    overflow_policy=str(self.config.buffering.overflow_policy),
                ),
                egress_adapter=self.egress_adapter,
            ),
        )

    async def _run_ingress(self) -> None:
        async for envelope in self.ingress_adapter.envelopes():
            if not isinstance(envelope, Envelope):
                continue
            await self.acs_bus.publish(envelope)

    async def shutdown(self) -> None:
        await self.acs_bus.shutdown()
        await self.provider_bus.shutdown()
        await self.provider_client.close()
        if self.egress_adapter:
            await self.egress_adapter.close()
        await self.ingress_adapter.close()


async def _main(config_path: Optional[str] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    config = DEFAULT_CONFIG
    if config_path:
        config = Config.from_yaml(Path(config_path))
    app = ServiceApp(config)
    try:
        await app.start()
    except KeyboardInterrupt:  # pragma: no cover - runtime guard
        logger.info("Received interrupt, shutting down")
    finally:
        await app.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run translation service core")
    parser.add_argument("--config", help="Path to YAML config", required=False)
    args = parser.parse_args()
    asyncio.run(_main(args.config))
