"""Completeness Score metric for translation evaluation.

Evaluates whether the translated text contains ALL information from the original text,
without omissions or additions, using LLM evaluation.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario
from production.services.llm_service import get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class CompletenessMetric(Metric):
    """Evaluate completeness of translation - ensures all information is preserved.

    Uses LLM (OpenAI) to evaluate whether the recognized text contains all the
    information present in the expected text, without omissions or additions.

    The metric:
    1. Extracts reference and hypothesis text from expectations and events
    2. Uses LLM to identify omissions and additions
    3. Evaluates information preservation
    4. Returns pass/fail based on 85% threshold

    Example:
        Expected: "Patient has hypertension, diabetes, and takes lisinopril daily"
        Hypothesis: "Patient has hypertension and takes lisinopril"
        → Omissions: ["diabetes", "daily"] → Score: 0.70 (missing key information)
    """

    name = "completeness"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 85.0
    ) -> None:
        """Initialize completeness metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 85)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate completeness for all transcript expectations.

        Returns:
            MetricResult with overall completeness score
        """
        turns_with_expectations = self.scenario.turns_to_evaluate()

        if not turns_with_expectations:
            return MetricResult(
                metric_name=self.name,
                score=100.0,
                reason="No transcript expectations to evaluate",
                details={"results": []}
            )

        # Initialize LLM service
        try:
            llm = get_llm_service()
        except Exception as e:
            return MetricResult(
                metric_name=self.name,
                score=0.0,
                reason=f"Failed to initialize LLM service: {e}",
                details={"error": str(e)}
            )

        results = []
        total_score = 0.0
        evaluations = 0

        for turn in turns_with_expectations:
            result = self._evaluate_expectation(turn, llm)
            results.append(result)

            if result["status"] == "evaluated":
                total_score += result["score"]
                evaluations += 1

        # Calculate overall score (0-100)
        overall_score = total_score / evaluations if evaluations > 0 else 0.0
        return MetricResult(
            metric_name=self.name,
            score=overall_score,
            reason=None,
            details={
                "threshold": self.threshold,
                "evaluations": evaluations,
                "turns": results
            }
        )

    def _evaluate_expectation(self, turn: ScenarioTurn, llm) -> dict:
        """Evaluate completeness for a single transcript expectation.

        Args:
            turn: Scenario turn with expected text
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Get reference text
        reference_text = turn.expected_text
        if not reference_text:
            return {
                "turn_id": turn.id,
                "status": "skipped",
                "reason": "No reference text provided"
            }

        # Find matching event
        turn_summary = self.conversation_manager.get_turn_summary(turn.id)
        hypothesis_text = turn_summary.translation_text() if turn_summary else None
        if not hypothesis_text:
            return {
                "turn_id": turn.id,
                "status": "failed",
                "reason": "No translated text found",
                "score": 0.0
            }

        # Call LLM to evaluate completeness
        llm_result = self._call_llm_evaluation(reference_text, hypothesis_text, llm)

        if not llm_result["success"]:
            return {
                "turn_id": turn.id,
                "status": "error",
                "reason": llm_result["error"],
                "score": 0.0
            }

        turn_score = llm_result["score"]

        return {
            "turn_id": turn.id,
            "status": "evaluated",
            "score": turn_score,
            "reasoning": llm_result["reasoning"],
            "omissions": llm_result["omissions"],
            "additions": llm_result["additions"],
            "reference_text": reference_text,
            "hypothesis_text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, reference: str, hypothesis: str, llm) -> dict:
        """Call LLM to evaluate completeness.

        Args:
            reference: Reference text (expected)
            hypothesis: Hypothesis text (recognized)
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for translation completeness.
Assess whether the recognized text contains ALL information from the expected text.

Consider:
- Are there any omissions (information in expected but missing in recognized)?
- Are there any additions (extra information not in expected)?
- Are all key facts, names, numbers, and details preserved?
- Is the information density comparable?
- If you find that there are missing sentences in the translation, that should dramatically reduce the score, even if it doesn't affect the overall meaning.

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0 to 100>,
    "reasoning": "<detailed explanation in English of what's complete, missing, or added>",
    "omissions": ["<missing element 1>", "<missing element 2>"],
    "additions": ["<extra element 1>", "<extra element 2>"]
}

Scoring guide:
- 100: Perfect - all information preserved, nothing missing or added
- 90-95: Excellent - minor detail missing or slight rephrasing
- 80-85: Good - one small element missing or added
- 70-75: Acceptable - some information missing but core preserved
- 50-65: Poor - significant omissions or additions
- <50: Very poor - major information loss or distortion"""

        user_prompt = f"""Expected text:
"{reference}"

Recognized text:
"{hypothesis}"

Evaluate the completeness of the recognized text."""

        # Make LLM call
        response = llm.call(
            prompt=user_prompt,
            system_prompt=system_prompt,
            response_format="json"
        )

        # Handle API errors
        if not response.success:
            return {
                "success": False,
                "error": response.error
            }

        # Parse response
        result_data = response.as_json()
        if not result_data:
            return {
                "success": False,
                "error": "Invalid JSON response from LLM"
            }

        # Extract results
        return {
            "success": True,
            "score": float(result_data.get("score", 0.0)),
            "reasoning": result_data.get("reasoning", ""),
            "omissions": result_data.get("omissions", []),
            "additions": result_data.get("additions", []),
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["CompletenessMetric"]
