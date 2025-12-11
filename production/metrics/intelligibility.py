"""Intelligibility metric for conversational quality evaluation.

Evaluates how clear, readable, and understandable the translated text is.
Uses LLM evaluation to score text clarity on a 1-5 scale, converted to 0-100%.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import LLMService, get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class IntelligibilityMetric(Metric):
    """Evaluate text clarity and readability.

    Uses LLM (OpenAI) to assess how clear, readable, and understandable
    the translated text is. Scores on a 1-5 scale, converted to 0-100%.

    The metric:
    1. Extracts translated text from collected events
    2. Uses LLM to evaluate intelligibility (clarity, readability)
    3. Converts 1-5 score to 0-100% scale: (score - 1) / 4 * 100
    4. Returns pass/fail based on 80% threshold (score of 4.2/5)

    Scoring guide (1-5):
        5: Perfect clarity, natural flow, easily understandable
        4: Clear and understandable, minor awkwardness
        3: Understandable but with awkward phrasing
        2: Difficult to understand, significant clarity issues
        1: Unintelligible, garbled, or incomprehensible text

    Example:
        Text: "I have chest pain and shortness of breath"
        → Score: 5/5 (100%) - Perfect clarity

        Text: "I have pain chest and breath short of"
        → Score: 2/5 (25%) - Word order issues, hard to understand
    """

    name = "intelligibility"

    def __init__(
        self,
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 0.80,
        model: Optional[str] = None
    ) -> None:
        """Initialize intelligibility metric.

        Args:
            expectations: Scenario expectations with reference texts
            conversation_manager: Conversation manager with per-turn summaries
            threshold: Minimum score to pass (default: 0.80 = 80% = 4.2/5)
            model: Optional LLM model override (default: from config)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold
        self.model = model

    def run(self) -> MetricResult:
        """Evaluate intelligibility for all transcript expectations.

        Returns:
            MetricResult with overall intelligibility score
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
            llm = get_llm_service() if not self.model else LLMService(model=self.model)
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
                total_score += result["score_normalized"]
                evaluations += 1

        # Calculate overall score (0-1 scale)
        overall_score = total_score / evaluations if evaluations > 0 else 0.0
        passed = overall_score >= self.threshold

        # Calculate average on 1-5 scale for reporting
        avg_score_1_5 = self._calculate_avg_raw_score(results)

        return MetricResult(
            metric_name=self.name,
            passed=passed,
            value=overall_score,
            reason=None if passed else f"Intelligibility {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results,
                # Session aggregates
                "avg_intelligibility_1_5": avg_score_1_5,
                "avg_intelligibility_0_100": overall_score * 100
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate intelligibility for a single transcript expectation.

        Args:
            expectation: Transcript expectation with event ID
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Get translated text from turn
        turn = self.conversation_manager.get_turn_summary(expectation.event_id)
        hypothesis_text = turn.translation_text() if turn else None

        if not hypothesis_text:
            return {
                "id": expectation.id,
                "event_id": expectation.event_id,
                "status": "failed",
                "reason": "No translated text found",
                "score_1_5": 1,
                "score_normalized": 0.0
            }

        # Call LLM to evaluate intelligibility
        llm_result = self._call_llm_evaluation(hypothesis_text, llm)

        if not llm_result["success"]:
            return {
                "id": expectation.id,
                "event_id": expectation.event_id,
                "status": "error",
                "reason": llm_result["error"],
                "score_1_5": 1,
                "score_normalized": 0.0
            }

        # Convert 1-5 to 0-1 scale: (score - 1) / 4
        # 1 → 0.0 (0%), 2 → 0.25 (25%), 3 → 0.5 (50%), 4 → 0.75 (75%), 5 → 1.0 (100%)
        score_1_5 = llm_result["intelligibility_score"]
        score_normalized = (score_1_5 - 1) / 4

        return {
            "id": expectation.id,
            "event_id": expectation.event_id,
            "status": "evaluated",
            "score_1_5": score_1_5,
            "score_normalized": score_normalized,
            "score_percentage": f"{score_normalized * 100:.2f}%",
            "passed": score_normalized >= self.threshold,
            "reasoning": llm_result["reasoning"],
            "text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, text: str, llm) -> dict:
        """Call LLM to evaluate intelligibility.

        Args:
            text: Text to evaluate
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for conversational quality.
Evaluate the INTELLIGIBILITY of the translated text.

Intelligibility measures how clear, readable, and understandable the text is.

Score from 1-5:
- 5: Perfect clarity, natural flow, easily understandable
- 4: Clear and understandable, minor awkwardness or grammatical issues
- 3: Understandable but with awkward phrasing or unnatural word order
- 2: Difficult to understand, significant clarity or grammatical issues
- 1: Unintelligible, garbled, or incomprehensible text

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "intelligibility_score": <integer 1-5>,
    "reasoning": "<brief explanation in English of the clarity assessment>"
}"""

        user_prompt = f"""Translated text:
"{text}"

Evaluate the intelligibility (clarity and readability) on a scale of 1-5."""

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

        # Extract and validate score
        score = result_data.get("intelligibility_score", 1)
        if not isinstance(score, int) or not (1 <= score <= 5):
            logger.warning(f"Invalid intelligibility score from LLM: {score}, defaulting to 1")
            score = 1

        return {
            "success": True,
            "intelligibility_score": score,
            "reasoning": result_data.get("reasoning", ""),
            "tokens_used": response.tokens_used,
            "model": response.model
        }

    def _calculate_avg_raw_score(self, results: list) -> float:
        """Calculate average score on 1-5 scale.

        Args:
            results: List of evaluation results

        Returns:
            Average score (1-5 scale)
        """
        evaluated = [r for r in results if r["status"] == "evaluated"]
        if not evaluated:
            return 0.0

        total = sum(r["score_1_5"] for r in evaluated)
        return round(total / len(evaluated), 2)


__all__ = ["IntelligibilityMetric"]
