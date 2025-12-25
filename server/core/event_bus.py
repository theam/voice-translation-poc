from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from .queues import BoundedQueue, OverflowPolicy

logger = logging.getLogger(__name__)


HandlerFn = Callable[[object], Awaitable[None]]


@dataclass
class HandlerConfig:
    name: str
    queue_max: int = 1000
    overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST
    concurrency: int = 1


@dataclass
class HandlerRuntime:
    config: HandlerConfig
    handler: HandlerFn
    queue: BoundedQueue[object]
    tasks: List[asyncio.Task]


class EventBus:
    """Fan-out event bus with independent per-handler queues."""

    def __init__(self, name: str):
        self.name = name
        self._handlers: Dict[str, HandlerRuntime] = {}
        self._lock = asyncio.Lock()

    async def register_handler(self, config: HandlerConfig, handler: HandlerFn) -> None:
        async with self._lock:
            if config.name in self._handlers:
                raise ValueError(f"Handler {config.name} already registered on bus {self.name}")
            queue = BoundedQueue(config.queue_max, config.overflow_policy)
            runtime = HandlerRuntime(config=config, handler=handler, queue=queue, tasks=[])
            runtime.tasks = [asyncio.create_task(self._worker(runtime), name=f"{config.name}-worker-{i}") for i in range(config.concurrency)]
            self._handlers[config.name] = runtime
            logger.info("Registered handler %s on bus %s with concurrency %s", config.name, self.name, config.concurrency)

    async def publish(self, envelope: object) -> None:
        async with self._lock:
            runtimes = list(self._handlers.values())
        for runtime in runtimes:
            enqueued = await runtime.queue.put(envelope)
            if not enqueued:
                logger.warning(
                    "Handler queue overflow on %s; policy=%s depth=%s", runtime.config.name, runtime.config.overflow_policy, len(runtime.queue)
                )

    async def _worker(self, runtime: HandlerRuntime) -> None:
        while True:
            try:
                envelope = await runtime.queue.get()
                await runtime.handler(envelope)
            except asyncio.CancelledError:
                logger.info("Worker for %s cancelled", runtime.config.name)
                break
            except Exception:
                logger.exception("Handler %s failed while processing envelope", runtime.config.name)

    async def shutdown(self) -> None:
        async with self._lock:
            runtimes = list(self._handlers.values())
        for runtime in runtimes:
            for task in runtime.tasks:
                task.cancel()
            await asyncio.gather(*runtime.tasks, return_exceptions=True)
        logger.info("Event bus %s shutdown complete", self.name)

