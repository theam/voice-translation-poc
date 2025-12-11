"""Completeness Score metric for translation evaluation.

Evaluates whether the translated text contains ALL information from the original text,
without omissions or additions, using LLM evaluation.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations, TranscriptExpectation
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
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 0.85
    ) -> None:
        """Initialize completeness metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 0.85 = 85%)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate completeness for all transcript expectations.

        Returns:
            MetricResult with overall completeness score
        """
        if not self.expectations.transcripts:
            return MetricResult(
                metric_name=self.name,
                passed=True,
                value=1.0,
                reason="No transcript expectations to evaluate",
                details={"results": []}
            )

        # Initialize LLM service
        try:
            llm = get_llm_service()
        except Exception as e:
            return MetricResult(
                metric_name=self.name,
                passed=False,
                value=0.0,
                reason=f"Failed to initialize LLM service: {e}",
                details={"error": str(e)}
            )

        results = []
        total_score = 0.0
        evaluations = 0

        for expectation in self.expectations.transcripts:
            result = self._evaluate_expectation(expectation, llm)
            results.append(result)

            if result["status"] == "evaluated":
                total_score += result["score"]
                evaluations += 1

        # Calculate overall score
        overall_score = total_score / evaluations if evaluations > 0 else 0.0
        passed = overall_score >= self.threshold

        return MetricResult(
            metric_name=self.name,
            passed=passed,
            value=overall_score,
            reason=None if passed else f"Completeness score {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate completeness for a single transcript expectation.

        Args:
            expectation: Transcript expectation with reference text
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Get reference text
        reference_text = expectation.expected_text
        if not reference_text:
            return {
                "id": expectation.id,
                "status": "skipped",
                "reason": "No reference text provided"
            }

        # Find matching event
        turn = self.conversation_manager.get_turn_summary(expectation.event_id)
        hypothesis_text = turn.translation_text() if turn else None
        if not hypothesis_text:
            return {
                "id": expectation.id,
                "status": "failed",
                "reason": "No translated text found",
                "score": 0.0
            }

        # Call LLM to evaluate completeness
        llm_result = self._call_llm_evaluation(reference_text, hypothesis_text, llm)

        if not llm_result["success"]:
            return {
                "id": expectation.id,
                "status": "error",
                "reason": llm_result["error"],
                "score": 0.0
            }

        return {
            "id": expectation.id,
            "status": "evaluated",
            "score": llm_result["score"],
            "passed": llm_result["score"] >= self.threshold,
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
    "score": <float 0.0 to 1.0>,
    "reasoning": "<detailed explanation in English of what's complete, missing, or added>",
    "omissions": ["<missing element 1>", "<missing element 2>"],
    "additions": ["<extra element 1>", "<extra element 2>"]
}

Scoring guide:
- 1.0: Perfect - all information preserved, nothing missing or added
- 0.9-0.95: Excellent - minor detail missing or slight rephrasing
- 0.8-0.85: Good - one small element missing or added
- 0.7-0.75: Acceptable - some information missing but core preserved
- 0.5-0.65: Poor - significant omissions or additions
- <0.5: Very poor - major information loss or distortion"""

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
