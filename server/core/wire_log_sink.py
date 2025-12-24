"""Wire log sink utilities for persisting raw WebSocket traffic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_WIRE_LOG_DIR = Path("./artifacts/websocket_wire")


class WireLogSink:
    """Write wire-level WebSocket messages to newline-delimited JSON."""

    def __init__(self, filename: str, base_dir: Path = DEFAULT_WIRE_LOG_DIR) -> None:
        base_path = base_dir if isinstance(base_dir, Path) else Path(base_dir)
        self.path = base_path / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_messages(self, messages: Iterable[Mapping]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for message in messages:
                handle.write(json.dumps(message))
                handle.write("\n")

    def append_message(self, message: Mapping) -> None:
        self.append_messages([message])


__all__ = ["WireLogSink", "DEFAULT_WIRE_LOG_DIR"]
