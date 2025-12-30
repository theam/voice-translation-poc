"""Wire log sink utilities for persisting raw WebSocket traffic."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


class WireLogSink:
    """Write wire-level WebSocket messages to newline-delimited JSON."""

    def __init__(self, name: str, base_dir: str) -> None:
        base_path = Path(base_dir)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.path = base_path / f"{name}.{timestamp}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_messages(self, messages: Iterable[Mapping]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for message in messages:
                handle.write(json.dumps(message))
                handle.write("\n")

    def append_message(self, message: Mapping) -> None:
        self.append_messages([message])


__all__ = ["WireLogSink"]
