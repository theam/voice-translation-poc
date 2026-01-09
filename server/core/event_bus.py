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
    pause_event: asyncio.Event


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
            pause_event = asyncio.Event()
            pause_event.set()
            runtime = HandlerRuntime(config=config, handler=handler, queue=queue, tasks=[], pause_event=pause_event)
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
                    "Handler queue overflow on %s; policy=%s depth=%s", runtime.config.name, runtime.config.overflow_policy, runtime.queue.qsize()
                )

    async def _worker(self, runtime: HandlerRuntime) -> None:
        while True:
            try:
                await runtime.pause_event.wait()

                envelope = await runtime.queue.get()
                await runtime.handler(envelope)
            except asyncio.CancelledError:
                logger.info("Worker for %s cancelled", runtime.config.name)
                break
            except Exception:
                logger.exception("Handler %s failed while processing envelope", runtime.config.name)

    async def pause(self, handler_name: str) -> None:
        async with self._lock:
            runtime = self._handlers.get(handler_name)
        if runtime is None:
            raise KeyError(f"Handler {handler_name} not registered on bus {self.name}")
        runtime.pause_event.clear()
        logger.info("Paused handler %s on bus %s", handler_name, self.name)

    async def resume(self, handler_name: str) -> None:
        async with self._lock:
            runtime = self._handlers.get(handler_name)
        if runtime is None:
            raise KeyError(f"Handler {handler_name} not registered on bus {self.name}")
        runtime.pause_event.set()
        logger.info("Resumed handler %s on bus %s", handler_name, self.name)

    async def clear(self, handler_name: str) -> int:
        async with self._lock:
            runtime = self._handlers.get(handler_name)
        if runtime is None:
            raise KeyError(f"Handler {handler_name} not registered on bus {self.name}")
        removed = await runtime.queue.clear()
        logger.info(
            "Cleared %d queued items for handler %s on bus %s",
            removed,
            handler_name,
            self.name,
        )
        return removed

    async def clear_all(self) -> dict[str, int]:
        async with self._lock:
            items = list(self._handlers.items())
        removed = {}
        for name, runtime in items:
            removed[name] = await runtime.queue.clear()
        return removed

    async def shutdown(self) -> None:
        async with self._lock:
            runtimes = list(self._handlers.values())
        for runtime in runtimes:
            runtime.pause_event.set()
            for task in runtime.tasks:
                task.cancel()
            await asyncio.gather(*runtime.tasks, return_exceptions=True)
        logger.info("Event bus %s shutdown complete", self.name)
