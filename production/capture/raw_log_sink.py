"""Persist raw SUT messages as JSON lines."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping


class RawLogSink:
    def __init__(self, base_dir: Path, filename: str) -> None:
        self.path = base_dir / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_messages(self, messages: Iterable[Mapping]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for message in messages:
                handle.write(json.dumps(message))
                handle.write("\n")

    def append_message(self, message: Mapping) -> None:
        self.append_messages([message])

__all__ = ["RawLogSink"]
