"""Calibration YAML file loader.

Loads and parses calibration configuration files.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Union

import yaml

from .models import CalibrationCase, CalibrationConfig, ConversationTurn


logger = logging.getLogger(__name__)


class CalibrationLoader:
    """Load and parse calibration YAML files.

    Handles loading individual files or entire directories of calibration configs.

    Example:
        >>> loader = CalibrationLoader()
        >>> config = loader.load_file("production/tests/calibration/intelligibility.yaml")
        >>> configs = loader.load_directory("production/tests/calibration")
    """

    def load_file(self, file_path: Union[Path, str]) -> CalibrationConfig:
        """Load single calibration file.

        Args:
            file_path: Path to calibration YAML file

        Returns:
            CalibrationConfig parsed from file

        Raises:
            FileNotFoundError: If file doesn't exist
            yaml.YAMLError: If YAML is malformed
            ValueError: If required fields are missing
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Calibration file not found: {file_path}")

        logger.info(f"Loading calibration file: {file_path}")

        with open(file_path, "r") as f:
            yaml_data = yaml.safe_load(f)

        config = self._parse_yaml(yaml_data)
        config.file_path = file_path

        logger.info(
            f"Loaded calibration config '{config.id}' with {len(config.calibration_cases)} cases"
        )

        return config

    def load_directory(self, dir_path: Union[Path, str]) -> List[CalibrationConfig]:
        """Load all calibration files from directory.

        Args:
            dir_path: Path to directory containing calibration YAML files

        Returns:
            List of CalibrationConfig objects

        Raises:
            FileNotFoundError: If directory doesn't exist
        """
        dir_path = Path(dir_path)

        if not dir_path.exists():
            raise FileNotFoundError(f"Calibration directory not found: {dir_path}")

        if not dir_path.is_dir():
            raise ValueError(f"Not a directory: {dir_path}")

        # Find all YAML files
        yaml_files = list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml"))

        if not yaml_files:
            logger.warning(f"No YAML files found in {dir_path}")
            return []

        logger.info(f"Found {len(yaml_files)} calibration files in {dir_path}")

        configs = []
        for yaml_file in sorted(yaml_files):
            try:
                config = self.load_file(yaml_file)
                configs.append(config)
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")
                # Continue loading other files

        logger.info(f"Successfully loaded {len(configs)} calibration configs")

        return configs

    def _parse_yaml(self, yaml_data: dict) -> CalibrationConfig:
        """Parse YAML data into CalibrationConfig.

        Args:
            yaml_data: Parsed YAML dictionary

        Returns:
            CalibrationConfig object

        Raises:
            ValueError: If required fields are missing
        """
        # Validate required fields
        required_fields = ["id", "version", "description", "metric", "created_at"]
        missing_fields = [field for field in required_fields if field not in yaml_data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # Parse calibration cases
        cases_data = yaml_data.get("calibration_cases", [])
        cases = [self._parse_case(case_data) for case_data in cases_data]

        # Build config
        return CalibrationConfig(
            id=yaml_data["id"],
            version=yaml_data["version"],
            description=yaml_data["description"],
            metric=yaml_data["metric"],
            created_at=yaml_data["created_at"],
            tags=yaml_data.get("tags", []),
            llm_config=yaml_data.get("llm_config"),
            calibration_cases=cases,
        )

    def _parse_case(self, case_data: dict) -> CalibrationCase:
        """Parse single calibration case from YAML.

        Args:
            case_data: Case dictionary from YAML

        Returns:
            CalibrationCase object

        Raises:
            ValueError: If required case fields are missing
        """
        # Validate required case fields
        required_fields = ["id", "description", "text", "metadata", "expected_scores"]
        missing_fields = [field for field in required_fields if field not in case_data]
        if missing_fields:
            raise ValueError(
                f"Case '{case_data.get('id', 'unknown')}' missing fields: {', '.join(missing_fields)}"
            )

        # Parse conversation history (for context metric)
        history_data = case_data.get("conversation_history", [])
        conversation_history = [self._parse_turn(turn_data) for turn_data in history_data]

        return CalibrationCase(
            id=case_data["id"],
            description=case_data["description"],
            text=case_data["text"],
            metadata=case_data["metadata"],
            expected_scores=case_data["expected_scores"],
            expected_reasoning=case_data.get("expected_reasoning"),
            conversation_history=conversation_history,
            expected_text=case_data.get("expected_text"),
        )

    def _parse_turn(self, turn_data: dict) -> ConversationTurn:
        """Parse conversation turn from YAML.

        Args:
            turn_data: Turn dictionary from YAML

        Returns:
            ConversationTurn object
        """
        return ConversationTurn(
            participant_id=turn_data["participant_id"],
            text=turn_data["text"],
            timestamp_ms=turn_data["timestamp_ms"],
            source_language=turn_data.get("source_language"),
            target_language=turn_data.get("target_language"),
        )


__all__ = ["CalibrationLoader"]
