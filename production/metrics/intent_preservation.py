"""Intent Preservation metric for translation evaluation.

Evaluates whether the speaker's communicative intent, purpose, and pragmatic goals
are preserved in the translation using LLM evaluation.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class IntentPreservationMetric(Metric):
    """Evaluate how well the communicative intent is preserved in translation.

    Uses LLM (OpenAI) to evaluate whether the speaker's intended message, purpose,
    and communicative goals are maintained in the recognized/translated text.

    The metric:
    1. Extracts reference and hypothesis text from expectations and events
    2. Uses LLM to identify the communicative intent in both texts
    3. Evaluates whether intent, tone, and pragmatic aspects are preserved
    4. Returns pass/fail based on 85% threshold

    Example:
        Expected: "Could you please help me with this?"
        Hypothesis: "Help me with this"
        → Intent changed from polite request to command → Score: 0.70
    """

    name = "intent_preservation"

    def __init__(
        self,
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 0.85
    ) -> None:
        """Initialize intent preservation metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 0.85 = 85%)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate intent preservation for all transcript expectations.

        Returns:
            MetricResult with overall intent preservation score
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
            reason=None if passed else f"Intent preservation score {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate intent preservation for a single transcript expectation.

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

        # Call LLM to evaluate intent preservation
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
            "expected_intent": llm_result["expected_intent"],
            "recognized_intent": llm_result["recognized_intent"],
            "intent_type": llm_result["intent_type"],
            "tone_match": llm_result["tone_match"],
            "pragmatic_issues": llm_result["pragmatic_issues"],
            "reference_text": reference_text,
            "hypothesis_text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, reference: str, hypothesis: str, llm) -> dict:
        """Call LLM to evaluate intent preservation.

        Args:
            reference: Reference text (expected)
            hypothesis: Hypothesis text (recognized)
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for communicative intent in translations.
Assess whether the speaker's intended message and purpose are preserved.

Consider:
- What is the speaker trying to communicate or achieve?
- Is it a question, statement, request, command, or expression?
- What is the tone and emotional content (if any)?
- Are implicit meanings and pragmatic aspects preserved?
- Would a listener understand the same intent from both versions?

Evaluate whether the recognized text conveys the same communicative intent as expected.

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0.0 to 1.0>,
    "reasoning": "<detailed explanation in English of how well intent is preserved>",
    "expected_intent": "<description of intent in expected text>",
    "recognized_intent": "<description of intent in recognized text>",
    "intent_type": "<question|statement|request|command|greeting|other>",
    "tone_match": <boolean>,
    "pragmatic_issues": ["<issue 1>", "<issue 2>"]
}

Scoring guide:
- 1.0: Perfect - intent completely preserved, listener would understand identically
- 0.9-0.95: Excellent - intent clear, minor tonal difference
- 0.8-0.85: Good - main intent preserved, some nuance lost
- 0.7-0.75: Acceptable - core intent recognizable but weakened
- 0.5-0.65: Poor - intent partially lost or ambiguous
- <0.5: Very poor - intent significantly altered or lost

Examples:
- "Could you help me?" vs "Help me" - different intent (polite request vs command)
- "I'm excited!" vs "I am excited" - same intent despite wording
- "What time is it?" vs "Tell me the time" - same intent, different form"""

        user_prompt = f"""Expected text:
"{reference}"

Recognized text:
"{hypothesis}"

Evaluate whether the communicative intent is preserved."""

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
            "expected_intent": result_data.get("expected_intent", ""),
            "recognized_intent": result_data.get("recognized_intent", ""),
            "intent_type": result_data.get("intent_type", "unknown"),
            "tone_match": result_data.get("tone_match", False),
            "pragmatic_issues": result_data.get("pragmatic_issues", []),
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["IntentPreservationMetric"]
