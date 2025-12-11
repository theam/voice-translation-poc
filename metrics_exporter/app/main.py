from __future__ import annotations

import logging
import time

from prometheus_client import REGISTRY, start_http_server

from .collector import MetricsCollector
from .config import ConfigError, load_config
from .mongo_access import MongoAccessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    accessor = MongoAccessor(config)
    collector = MetricsCollector(accessor, config)

    REGISTRY.register(collector)
    start_http_server(config.port)
    logger.info("Metrics exporter started on port %s", config.port)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down metrics exporter")


if __name__ == "__main__":
    main()
