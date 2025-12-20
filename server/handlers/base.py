from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models.envelope import Envelope


@dataclass
class HandlerSettings:
    name: str
    queue_max: int
    overflow_policy: str
    concurrency: int = 1


class Handler:
    """Base handler contract."""

    def __init__(self, settings: HandlerSettings):
        self.settings = settings

    async def __call__(self, envelope: Envelope) -> None:  # pragma: no cover - interface
        await self.handle(envelope)

    async def handle(self, envelope: Envelope) -> None:  # pragma: no cover - to be implemented
        raise NotImplementedError

