"""Wire log scenario loader."""
from __future__ import annotations

import logging
from pathlib import Path

from production.scenario_engine.models import Scenario, Participant, ScenarioTurn

logger = logging.getLogger(__name__)


class WireLogScenarioLoader:
    """Load wire log JSONL file and convert to Scenario."""

    def load(self, wire_log_path: Path) -> Scenario:
        """Load wire log and create Scenario with turns at 0ms.

        Args:
            wire_log_path: Path to wire log JSONL file

        Returns:
            Scenario object with single turn pointing to wire log file
        """
        if not wire_log_path.exists():
            raise FileNotFoundError(f"Wire log file not found: {wire_log_path}")

        logger.info("Creating scenario for wire log: %s", wire_log_path.name)

        # Create generic "replay" participant
        participants = {
            "replay": Participant(
                name="replay",
                source_language="auto",
                target_language="auto",
                audio_files={},
            )
        }

        # Create SINGLE turn pointing to wire log file
        # The ReplayWireLogTurnProcessor will parse and replay the messages
        turn = ScenarioTurn(
            id="replay",
            type="replay_wire_log",
            participant="replay",
            start_at_ms=0,  # CRITICAL: No silence before this turn
            data_file=str(wire_log_path),  # Path to wire log file
        )

        scenario = Scenario(
            id=f"replay_{wire_log_path.stem}",
            description=f"Wire log replay: {wire_log_path.name}",
            participants=participants,
            turns=[turn],
            tags=["replay"],
            metrics=[],  # CRITICAL: Empty list = run NO metrics
            tail_silence=0,  # CRITICAL: No tail silence - already in wire log
        )

        return scenario
