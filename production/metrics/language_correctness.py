"""Language Correctness metric for translation evaluation.

Verifies that each sentence in the recognized text matches the LANGUAGE of the
corresponding sentence in the expected text in bilingual/multilingual conversations.
"""
from __future__ import annotations

import logging
from typing import Sequence

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class LanguageCorrectnessMetric(Metric):
    """Assess if each sentence in the recognized text matches the language of the expected text.

    In bilingual/multilingual conversations where speakers use different languages,
    this metric verifies that each sentence in the recognized text matches the
    LANGUAGE of the corresponding sentence in the expected text.

    CRITICAL: This metric ONLY checks that languages match, NOT semantic accuracy,
    completeness, or translation quality. A sentence can be semantically incorrect
    but still pass if it's in the same language as expected.

    The metric:
    1. Splits both texts into sentences
    2. Intelligently matches corresponding sentences (handles omissions)
    3. Detects language of each sentence
    4. Verifies recognized sentence is in SAME language as expected
    5. Returns pass/fail based on 100% threshold (all matched sentences must match language)

    Example:
        Expected: "Hello, how are you? Estoy bien."
        Hypothesis: "Hello, how are you? I'm fine."
        → Sentence 1: English ✓ (match)
        → Sentence 2: Spanish → English ✗ (fail)
        → Score: 0.50 (50%) → FAIL (needs 100%)
    """

    name = "language_correctness"

    def __init__(
        self,
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 1.0
    ) -> None:
        """Initialize language correctness metric.

        Args:
            expectations: Scenario expectations with reference texts
            events: Collected events from scenario execution
            threshold: Minimum score to pass (default: 1.0 = 100%, all must match)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate language correctness for all transcript expectations.

        Returns:
            MetricResult with overall language correctness score
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
            reason=None if passed else f"Language correctness score {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate language correctness for a single transcript expectation.

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

        # Call LLM to evaluate language correctness
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
            "sentence_pairs": llm_result["sentence_pairs"],
            "correct_count": llm_result["correct_count"],
            "total_count": llm_result["total_count"],
            "missing_count": llm_result["missing_count"],
            "missing_sentences": llm_result["missing_sentences"],
            "issues": llm_result["issues"],
            "reference_text": reference_text,
            "hypothesis_text": hypothesis_text,
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation(self, reference: str, hypothesis: str, llm) -> dict:
        """Call LLM to evaluate language correctness.

        Args:
            reference: Reference text (expected)
            hypothesis: Hypothesis text (recognized)
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for translation language correctness.
Your task is to verify that each sentence in the recognized text matches the language of the corresponding sentence in the expected text.

In a bilingual conversation where speakers use different languages:
- If an expected sentence is in English, the recognized sentence should also be in English
- If an expected sentence is in Spanish, the recognized sentence should also be in Spanish
- The recognized text should preserve the language of each sentence from the expected text

CRITICAL: This metric ONLY checks that languages match, NOT semantic accuracy, completeness, or translation quality.
A sentence can be semantically incorrect but still pass if it's in the same language as expected.

IMPORTANT: The recognized text OFTEN has missing sentences. You MUST intelligently match sentences even when some are omitted.
Use semantic similarity and context to identify which recognized sentence corresponds to which expected sentence.

Steps:
1. Split both expected and recognized text into sentences
2. For each expected sentence, find the corresponding recognized sentence using semantic similarity, context, and position
   - If a sentence is missing in recognized, skip that pair (don't count it in scoring)
   - Use semantic meaning to match sentences even when wording differs
3. Detect the language of each expected sentence
4. Detect the language of each corresponding recognized sentence
5. Verify that recognized sentence is in the SAME language as expected sentence

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "sentence_pairs": [
        {
            "expected_sentence": "<sentence from expected text>",
            "recognized_sentence": "<corresponding sentence from recognized text, or 'MISSING' if not found>",
            "expected_language": "<ISO 639-1 code, e.g., 'en', 'es'>",
            "recognized_language": "<ISO 639-1 code, e.g., 'en', 'es', or 'MISSING' if sentence not found>",
            "is_correctly_translated": <boolean, false if missing or languages don't match>,
            "issue": "<description if languages don't match or sentence is missing, empty string if correct>"
        }
    ],
    "score": <float 0.0 to 1.0, proportion of matched sentences with matching languages>,
    "correct_count": <integer, number of matched sentences with matching languages>,
    "total_count": <integer, total number of matched sentence pairs (exclude missing sentences)>,
    "missing_count": <integer, number of expected sentences that were not found in recognized text>,
    "reasoning": "<brief explanation in English of the evaluation, including how sentences were matched>"
}

Scoring:
- Only include sentence pairs where a recognized sentence was found (exclude missing sentences from scoring)
- score: Proportion of matched sentences where recognized_language == expected_language (they match)
- A sentence passes if recognized_language == expected_language (they are the same)
- A sentence fails if recognized_language != expected_language (they are different)
- Missing sentences are excluded from the score calculation but should be noted in the reasoning"""

        user_prompt = f"""Expected text:
"{reference}"

Recognized text:
"{hypothesis}"

For each sentence in the expected text, find the corresponding sentence in the recognized text
and verify that it is in the SAME language. Evaluate language matching correctness."""

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
        sentence_pairs = result_data.get("sentence_pairs", [])
        score = float(result_data.get("score", 0.0))
        correct_count = int(result_data.get("correct_count", 0))
        total_count = int(result_data.get("total_count", 0))
        missing_count = int(result_data.get("missing_count", 0))
        reasoning = result_data.get("reasoning", "")

        # Collect issues for details
        issues = []
        missing_sentences = []
        for pair in sentence_pairs:
            recognized_sentence = pair.get("recognized_sentence", "")
            recognized_lang = pair.get("recognized_language", "")

            # Check if sentence is missing
            if recognized_sentence == "MISSING" or recognized_lang == "MISSING":
                missing_sentences.append({
                    "expected": pair.get("expected_sentence", ""),
                    "expected_lang": pair.get("expected_language", ""),
                })
            elif not pair.get("is_correctly_translated", False):
                issue = pair.get("issue", "Languages do not match")
                issues.append({
                    "expected": pair.get("expected_sentence", ""),
                    "recognized": recognized_sentence,
                    "expected_lang": pair.get("expected_language", ""),
                    "recognized_lang": recognized_lang,
                    "issue": issue
                })

        return {
            "success": True,
            "score": score,
            "reasoning": reasoning,
            "sentence_pairs": sentence_pairs,
            "correct_count": correct_count,
            "total_count": total_count,
            "missing_count": missing_count,
            "missing_sentences": missing_sentences,
            "issues": issues,
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["LanguageCorrectnessMetric"]
