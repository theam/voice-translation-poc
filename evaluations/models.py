"""Data models for evaluation system."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

import yaml

from metrics import MetricResult


DEFAULT_PARTICIPANT_ID = "4:+34646783858"


@dataclass
class TestCase:
    """Represents a single test case from the YAML configuration."""
    id: str
    name: str
    audio_file: Path
    expected_text: str
    language: str
    participant_id: str
    enabled: bool
    metadata: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict, base_path: Path) -> "TestCase":
        """Create TestCase from dictionary, resolving relative paths."""
        audio_path = base_path / data["audio_file"]

        # Handle expected_text as file path or direct string
        expected_text = data["expected_text"]
        if expected_text.startswith("./") or expected_text.startswith("/"):
            text_path = base_path / expected_text
            if text_path.exists():
                with open(text_path, 'r') as f:
                    expected_text = f.read().strip()

        return cls(
            id=data["id"],
            name=data["name"],
            audio_file=audio_path,
            expected_text=expected_text,
            language=data.get("language", "en-US"),
            participant_id=data.get("participant_id", DEFAULT_PARTICIPANT_ID),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {})
        )


@dataclass
class TestConfig:
    """Configuration loaded from YAML file."""
    test_cases: List[TestCase]
    defaults: Dict[str, Any]
    server: Dict[str, Any]

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "TestConfig":
        """Load test configuration from YAML file."""
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        base_path = yaml_path.parent
        test_cases = [
            TestCase.from_dict(tc, base_path)
            for tc in data.get("test_cases", [])
        ]

        return cls(
            test_cases=test_cases,
            defaults=data.get("defaults", {}),
            server=data.get("server", {"host": "localhost", "port": 8080})
        )


@dataclass
class TestResult:
    """Results from executing a single test case."""
    test_case: TestCase
    success: bool
    chunks_sent: int
    response_time_ms: float
    azure_responses: List[Dict[str, Any]]
    recognized_text: str = ""
    translations: Dict[str, str] = field(default_factory=dict)
    error_details: Optional[str] = None
    latency_ms: Optional[float] = None  # Time from first chunk sent to first text delta received


@dataclass
class TestReport:
    """Complete test report with all results."""
    timestamp: datetime
    test_cases: List[TestCase] = field(default_factory=list)
    test_results: Dict[str, TestResult] = field(default_factory=dict)
    metric_results: Dict[str, Dict[str, MetricResult]] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
