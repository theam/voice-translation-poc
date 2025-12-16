"""Target language verification metric."""
from __future__ import annotations

import logging
from typing import List, Optional

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario, ScenarioTurn
from production.services.llm_service import get_llm_service

from .base import Metric, MetricResult

logger = logging.getLogger(__name__)


class TargetLanguageMetric(Metric):
    """Verify translated text is in the expected target language per turn."""

    name = "target_language"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        model: Optional[str] = None,
    ) -> None:
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.model = model

    def run(self) -> MetricResult:
        """Evaluate target language correctness for each turn."""
        turns_with_expected_language: List[ScenarioTurn] = [
            t for t in self.scenario.turns if t.expected_language
        ]

        if not turns_with_expected_language:
            return MetricResult(
                metric_name=self.name,
                score=100.0,
                reason="No target language expectations to evaluate",
                details={"results": []},
            )

        try:
            llm = get_llm_service() if not self.model else get_llm_service(model=self.model)
        except Exception as e:  # noqa: BLE001
            return MetricResult(
                metric_name=self.name,
                score=0.0,
                reason=f"Failed to initialize LLM service: {e}",
                details={"error": str(e)},
            )

        results = []
        total_score = 0.0
        evaluations = 0

        # Map scenario turns for lookup
        scenario_turns = {t.id: t for t in self.scenario.turns}

        for turn_summary in self.conversation_manager.iter_turns():
            scenario_turn = scenario_turns.get(turn_summary.turn_id)
            if not scenario_turn or not scenario_turn.expected_language:
                continue

            translated_text = turn_summary.translation_text()
            if not translated_text:
                results.append(
                    {
                        "turn_id": turn_summary.turn_id,
                        "status": "failed",
                        "score": 0.0,
                        "reason": "No translated text found",
                        "expected_language": scenario_turn.expected_language,
                    }
                )
                continue

            llm_result = self._detect_language(translated_text, llm)
            if not llm_result["success"]:
                results.append(
                    {
                        "turn_id": turn_summary.turn_id,
                        "status": "error",
                        "score": 0.0,
                        "reason": llm_result["error"],
                        "expected_language": scenario_turn.expected_language,
                    }
                )
                continue

            detected_language = llm_result["language_code"]
            matches = detected_language.lower() == scenario_turn.expected_language.lower()
            score = 100.0 if matches else 0.0

            results.append(
                {
                    "turn_id": turn_summary.turn_id,
                    "status": "evaluated",
                    "score": score,
                    "expected_language": scenario_turn.expected_language,
                    "detected_language": detected_language,
                    "reasoning": llm_result["reasoning"],
                }
            )

            total_score += score
            evaluations += 1

        overall_score = total_score / evaluations if evaluations > 0 else 0.0

        return MetricResult(
            metric_name=self.name,
            score=overall_score,
            details={
                "threshold": 100.0,  # Language match is binary (0 or 100)
                "evaluations": evaluations,
                "turns": results,
            },
        )

    def _detect_language(self, text: str, llm) -> dict:
        """Use LLM to detect language of the provided text."""
        system_prompt = (
            "You are an expert language identifier. Detect the primary language code (ISO 639-1) of the text."
        )
        user_prompt = f"""Text:
"{text}"

Respond ONLY with valid JSON:
{{
    "language_code": "<iso 639-1 code>",
    "reasoning": "<brief explanation of your detection>"
}}
"""
        try:
            response = llm.call(prompt=user_prompt, system_prompt=system_prompt)
            if not response.success:
                return {"success": False, "error": response.error}

            result_data = response.as_json()
            return {
                "success": True,
                "language_code": result_data.get("language_code", "").strip(),
                "reasoning": result_data.get("reasoning", ""),
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Language detection failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}


__all__ = ["TargetLanguageMetric"]
