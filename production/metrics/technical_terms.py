"""Technical Terms Accuracy metric for translation evaluation.

Evaluates whether technical terms, proper nouns, acronyms, and specialized vocabulary
are correctly preserved/translated in the recognized text using LLM evaluation.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations, TranscriptExpectation
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
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 0.90
    ) -> None:
        """Initialize technical terms metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 0.90 = 90%)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate technical terms preservation for all transcript expectations.

        Returns:
            MetricResult with overall technical terms accuracy
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
            reason=None if passed else f"Technical terms score {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate technical terms for a single transcript expectation.

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

        # Call LLM to evaluate technical terms
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
    "score": <float 0.0 to 1.0>,
    "reasoning": "<detailed explanation in English of technical term handling>",
    "technical_terms_found": ["<term 1>", "<term 2>"],
    "correct_terms": ["<correctly handled term 1>", "<term 2>"],
    "incorrect_terms": [
        {"expected": "<term in expected>", "recognized": "<term in recognized or 'missing'>"}
    ],
    "has_technical_content": <boolean>
}

Scoring guide:
- 1.0: All technical terms perfect
- 0.9-0.95: Excellent - minor variation in non-critical term
- 0.8-0.85: Good - one term slightly incorrect but understandable
- 0.7-0.75: Acceptable - some terms wrong but meaning preserved
- 0.5-0.65: Poor - multiple critical terms incorrect
- <0.5: Very poor - major terminology errors

Special case: If no technical terms exist, return score 1.0 with has_technical_content: false"""

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
