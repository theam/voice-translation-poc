"""Segmentation metric for conversational quality evaluation.

Evaluates whether sentence boundaries and turn segmentation are correct.
Uses LLM evaluation to score text segmentation on a 0-100 scale (0 = no boundaries, 100 = perfect segmentation).
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario
from production.services.llm_service import LLMService, get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class SegmentationMetric(Metric):
    """Evaluate sentence boundaries and turn segmentation.

    Uses LLM (OpenAI) to assess whether the text has proper sentence boundaries,
    appropriate turn segmentation, and natural breaks. Scores on a 0-100 scale.

    The metric:
    1. Extracts translated text from collected events
    2. Uses LLM to evaluate segmentation (sentence breaks, turn boundaries) on a 0-100 scale
    3. Returns pass/fail based on 80 threshold

    Scoring guide (0-100 scale):
        100: Perfect segmentation, natural sentence breaks and turn boundaries
        75-99: Good segmentation, one minor split or merge issue
        50-74: Acceptable segmentation, multiple minor issues but understandable
        25-49: Poor segmentation, sentences incorrectly split or merged
        0-24: Severely fragmented or run-on text with no clear boundaries

    Example:
        Text: "Hello, how are you? I'm doing well today."
        → Score: 1.0 - Perfect sentence boundaries

        Text: "Hello how are you I'm doing well today"
        → Score: 0.25 - Missing punctuation, run-on sentence

        Text: "Hello. How. Are. You. I'm. Doing. Well."
        → Score: 0.25 - Over-segmented, unnatural breaks
    """

    name = "segmentation"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 80.0,
        model: Optional[str] = None
    ) -> None:
        """Initialize segmentation metric.

        Args:
            expectations: Scenario expectations with reference texts
            conversation_manager: Conversation manager with per-turn summaries
            threshold: Minimum score to pass (default: 80 on 0-100 scale)
            model: Optional LLM model override (default: from config)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold
        self.model = model

    def run(self) -> MetricResult:
        """Evaluate segmentation for all transcript expectations.

        Returns:
            MetricResult with overall segmentation score
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
            llm = get_llm_service() if not self.model else LLMService(model=self.model)
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

        # Calculate overall score (0-100 scale)
        overall_score = total_score / evaluations if evaluations > 0 else 0.0

        return MetricResult(
            metric_name=self.name,
            score=overall_score,
            details={
                "threshold": self.threshold,
                "evaluations": evaluations,
                "turns": results,
            }
        )

    def _evaluate_expectation(self, turn: ScenarioTurn, llm) -> dict:
        """Evaluate segmentation for a single transcript expectation.

        Args:
            turn: Scenario turn with expected text
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Get translated text from turn
        turn_summary = self.conversation_manager.get_turn_summary(turn.id)
        hypothesis_text = turn_summary.translation_text() if turn_summary else None

        if not hypothesis_text:
            return {
                "turn_id": turn.id,
                "status": "failed",
                "reason": "No translated text found",
                "score": 0.0
            }

        # Call LLM to evaluate segmentation
        llm_result = self._call_llm_evaluation(hypothesis_text, llm)

        if not llm_result["success"]:
            return {
                "turn_id": turn.id,
                "status": "error",
                "reason": llm_result["error"],
                "score": 0.0
            }

        # LLM returns 0-100
        score = llm_result["score"]

        return {
            "turn_id": turn.id,
            "status": "evaluated",
            "score": score,
            "reasoning": llm_result["reasoning"],
            "text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, text: str, llm) -> dict:
        """Call LLM to evaluate segmentation.

        Args:
            text: Text to evaluate
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for conversational quality.
Evaluate the SEGMENTATION of the translated text.

Segmentation measures whether sentence boundaries and turn segmentation are correct,
with appropriate punctuation and natural breaks.

Score from 0 to 100:
- 100: Perfect segmentation, natural sentence breaks and turn boundaries
- 75-99: Good segmentation, one minor split or merge issue
- 50-74: Acceptable segmentation, multiple minor issues but understandable
- 25-49: Poor segmentation, sentences incorrectly split or merged, missing punctuation
- 0-24: Severely fragmented or run-on text with no clear sentence boundaries

Consider:
- Are sentence boundaries properly marked with punctuation?
- Is the text appropriately segmented (not over-fragmented, not run-on)?
- Are turn boundaries natural and clear?
- Is punctuation (periods, commas, question marks) used correctly?

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0-100>,
    "reasoning": "<brief explanation in English of the segmentation assessment>"
}"""

        user_prompt = f"""Translated text:
"{text}"

Evaluate the segmentation (sentence boundaries and turn segmentation) on a scale of 0 to 100."""

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

        return {
            "success": True,
            "score": float(result_data.get("score", 0.0)),
            "reasoning": result_data.get("reasoning", ""),
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["SegmentationMetric"]
