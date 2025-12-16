"""Scenario file loader for YAML/JSON definitions."""
from __future__ import annotations

import json
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from production.scenario_engine.models import (
    Event,
    Expectations,
    Participant,
    Scenario,
    TranscriptExpectation,
)

logger = logging.getLogger(__name__)


class ScenarioLoader:
    """Load scenario definitions into strongly typed dataclasses."""

    def __init__(self, base_path: Optional[Path] = None) -> None:
        self.base_path = base_path or Path.cwd()

    def load(self, path: Path) -> Scenario:
        raw = self._load_raw(path)
        participants = {
            name: Participant(
                name=name,
                source_language=data.get("source_language", ""),
                target_language=data.get("target_language", ""),
                audio_files={k: self._resolve_path(v) for k, v in (data.get("audio_files") or {}).items()},
            )
            for name, data in (raw.get("participants") or {}).items()
        }

        events = [
            Event(
                id=item["id"],
                type=item["type"],
                participant=item["participant"],
                audio_file=item.get("audio_file"),
                start_at_ms=int(item.get("start_at_ms", 0)),
                barge_in=bool(item.get("barge_in", False)),
            )
            for item in raw.get("events", [])
        ]

        transcript_expectations = [
            TranscriptExpectation(
                id=exp["id"],
                event_id=exp["event_id"],
                source_language=exp["source_language"],
                target_language=exp["target_language"],
                expected_text=exp.get("expected_text"),
                regex=exp.get("regex"),
                wer_threshold=exp.get("wer_threshold"),
            )
            for exp in raw.get("expectations", {}).get("transcripts", [])
        ]

        expectations = Expectations(
            transcripts=transcript_expectations,
            sequence=raw.get("expectations", {}).get("sequence", []),
            max_latency_ms=raw.get("expectations", {}).get("max_latency_ms"),
        )

        scenario = Scenario(
            id=raw["id"],
            description=raw.get("description", ""),
            participants=participants,
            events=events,
            expectations=expectations,
            tags=raw.get("tags", []),
        )

        logger.info(f"Scenario loaded id:{scenario.id} path:{path}")
        return scenario

    def _load_raw(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)

        suffix = path.suffix.lower()
        content = path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            try:
                yaml = importlib.import_module("yaml")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "PyYAML is required to load YAML scenarios. Install it via 'poetry install --with evaluations' or add it to your environment."
                ) from exc
            return yaml.safe_load(content) or {}
        if suffix == ".json":
            return json.loads(content)
        raise ValueError(f"Unsupported scenario file type: {suffix}")

    def _resolve_path(self, value: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        return (self.base_path / candidate).resolve()


__all__ = ["ScenarioLoader"]
