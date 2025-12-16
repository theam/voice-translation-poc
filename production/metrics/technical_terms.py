"""Technical Terms Accuracy metric for translation evaluation.

Evaluates whether technical terms, proper nouns, acronyms, and specialized vocabulary
are correctly preserved/translated in the recognized text using LLM evaluation.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario
from production.services.llm_service import get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class TechnicalTermsMetric(Metric):
    """Evaluate accuracy of technical terms, proper nouns, and specialized vocabulary.

    Uses LLM (OpenAI) to identify and evaluate whether technical terms, proper names,
    acronyms, and domain-specific vocabulary are correctly translated/preserved.

    The metric:
    1. Extracts reference and hypothesis text from expectations and events
    2. Uses LLM to identify technical terms in both texts
    3. Evaluates whether terms are correctly preserved/translated
    4. Returns pass/fail based on 90% threshold (higher bar than general text)

    Example:
        Reference: "Patient has hypertension and takes lisinopril"
        Hypothesis: "Patient has high blood pressure and takes lisinopril"
        → Score: 0.5 (hypertension mistranslated, lisinopril correct)
    """

    name = "technical_terms"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 90.0
    ) -> None:
        """Initialize technical terms metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 90)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate technical terms preservation for all transcript expectations.

        Returns:
            MetricResult with overall technical terms accuracy
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
        """Evaluate technical terms for a single transcript expectation.

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

        # Call LLM to evaluate technical terms
        llm_result = self._call_llm_evaluation(reference_text, hypothesis_text, llm)

        if not llm_result["success"]:
            return {
                "turn_id": turn.id,
                "status": "error",
                "reason": llm_result["error"],
                "score": 0.0
            }

        return {
            "turn_id": turn.id,
            "status": "evaluated",
            "score": llm_result["score"],
            "reasoning": llm_result["reasoning"],
            "technical_terms_found": llm_result["technical_terms_found"],
            "correct_terms": llm_result["correct_terms"],
            "incorrect_terms": llm_result["incorrect_terms"],
            "has_technical_content": llm_result["has_technical_content"],
            "reference_text": reference_text,
            "hypothesis_text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, reference: str, hypothesis: str, llm) -> dict:
        """Call LLM to evaluate technical terms preservation.

        Args:
            reference: Reference text (expected)
            hypothesis: Hypothesis text (recognized)
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for technical terminology accuracy in translations.
Identify and assess technical terms, proper nouns, acronyms, and specialized vocabulary.

Consider:
- Proper names (people, places, companies, brands)
- Technical terminology (medical, legal, scientific, business)
- Numbers, dates, and measurements
- Acronyms and abbreviations
- Domain-specific vocabulary

Evaluate whether these terms are correctly preserved/translated in the recognized text.

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0 to 100>,
    "reasoning": "<detailed explanation in English of technical term handling>",
    "technical_terms_found": ["<term 1>", "<term 2>"],
    "correct_terms": ["<correctly handled term 1>", "<term 2>"],
    "incorrect_terms": [
        {"expected": "<term in expected>", "recognized": "<term in recognized or 'missing'>"}
    ],
    "has_technical_content": <boolean>
}

Scoring guide:
- 100: All technical terms perfect
- 90-95: Excellent - minor variation in non-critical term
- 80-85: Good - one term slightly incorrect but understandable
- 70-75: Acceptable - some terms wrong but meaning preserved
- 50-65: Poor - multiple critical terms incorrect
- <50: Very poor - major terminology errors

Special case: If no technical terms exist, return score 100 with has_technical_content: false"""

        user_prompt = f"""Expected text:
"{reference}"

Recognized text:
"{hypothesis}"

Identify and evaluate all technical terms, proper nouns, and specialized vocabulary."""

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
            "technical_terms_found": result_data.get("technical_terms_found", []),
            "correct_terms": result_data.get("correct_terms", []),
            "incorrect_terms": result_data.get("incorrect_terms", []),
            "has_technical_content": result_data.get("has_technical_content", True),
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["TechnicalTermsMetric"]
