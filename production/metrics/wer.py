"""Word Error Rate (WER) metric for translation accuracy evaluation.

WER measures the accuracy of Automatic Speech Recognition (ASR) and translation
by comparing the recognized text against a reference transcription.

Formula: WER = (S + D + I) / N
Where:
    S = Substitutions (words replaced)
    D = Deletions (words removed)
    I = Insertions (words added)
    N = Number of words in reference
"""
from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario
from production.utils.text_normalization import normalize_text_for_wer

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


def _tokenize(text: str, normalize: bool = True, language: str = "en") -> List[str]:
    """Tokenize text into words with optional normalization.

    Args:
        text: Input text to tokenize
        normalize: Whether to apply contraction expansion and normalization
        language: Language code for language-specific normalization

    Returns:
        List of normalized word tokens
    """
    if normalize:
        # Apply full normalization (contractions, lowercase, punctuation)
        text = normalize_text_for_wer(text, language)
    else:
        # Basic normalization only
        text = text.lower().strip()

    return text.split()


def _calculate_edit_distance(reference: List[str], hypothesis: List[str]) -> Tuple[int, int, int, int]:
    """Calculate Levenshtein distance with edit operations breakdown.

    Uses dynamic programming to compute the minimum edit distance and
    backtracks to count specific operations (substitutions, deletions, insertions).

    Args:
        reference: Reference word sequence (ground truth)
        hypothesis: Hypothesis word sequence (ASR output)

    Returns:
        Tuple of (substitutions, deletions, insertions, total_distance)
    """
    ref_len = len(reference)
    hyp_len = len(hypothesis)

    # Initialize DP matrix: dp[i][j] = edit distance between reference[:i] and hypothesis[:j]
    dp = [[0] * (hyp_len + 1) for _ in range(ref_len + 1)]

    # Base cases: converting empty string to prefix
    for i in range(ref_len + 1):
        dp[i][0] = i  # Delete all words from reference
    for j in range(hyp_len + 1):
        dp[0][j] = j  # Insert all words into empty string

    # Fill DP table
    for i in range(1, ref_len + 1):
        for j in range(1, hyp_len + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                # Words match, no operation needed
                dp[i][j] = dp[i - 1][j - 1]
            else:
                # Take minimum of:
                # - Substitution: dp[i-1][j-1] + 1
                # - Deletion: dp[i-1][j] + 1
                # - Insertion: dp[i][j-1] + 1
                dp[i][j] = min(
                    dp[i - 1][j - 1] + 1,  # Substitution
                    dp[i - 1][j] + 1,      # Deletion
                    dp[i][j - 1] + 1       # Insertion
                )

    # Backtrack to count operations
    substitutions = 0
    deletions = 0
    insertions = 0

    i, j = ref_len, hyp_len
    while i > 0 or j > 0:
        if i == 0:
            # Only insertions left
            insertions += j
            break
        elif j == 0:
            # Only deletions left
            deletions += i
            break
        elif reference[i - 1] == hypothesis[j - 1]:
            # Match, move diagonally
            i -= 1
            j -= 1
        else:
            # Find which operation was taken
            current = dp[i][j]
            diagonal = dp[i - 1][j - 1] if i > 0 and j > 0 else float('inf')
            left = dp[i][j - 1] if j > 0 else float('inf')
            up = dp[i - 1][j] if i > 0 else float('inf')

            if diagonal <= left and diagonal <= up:
                # Substitution
                substitutions += 1
                i -= 1
                j -= 1
            elif left <= up:
                # Insertion
                insertions += 1
                j -= 1
            else:
                # Deletion
                deletions += 1
                i -= 1

    total_distance = dp[ref_len][hyp_len]
    return substitutions, deletions, insertions, total_distance


def _interpret_wer(wer: float) -> str:
    """Provide human-readable interpretation of WER value.

    Args:
        wer: Word Error Rate value

    Returns:
        Interpretation string
    """
    if wer == 0.0:
        return "Perfect recognition"
    elif wer <= 0.05:
        return "Excellent (< 5% error)"
    elif wer <= 0.15:
        return "Good (5-15% error)"
    elif wer <= 0.30:
        return "Acceptable (15-30% error)"
    elif wer <= 0.50:
        return "Poor (30-50% error)"
    else:
        return "Very poor (> 50% error)"


class WERMetric(Metric):
    """Calculate Word Error Rate (WER) for ASR/translation accuracy.

    WER measures the percentage of words that were incorrectly recognized
    compared to the reference transcription. It's the standard metric for
    evaluating ASR systems.

    The metric:
    1. Extracts reference text from scenario expectations
    2. Finds corresponding translated text from collected events
    3. Calculates WER using Levenshtein distance
    4. Applies text normalization for robustness

    Example:
        Reference: "tengo dolor de pecho"
        Translation: "tengo color de pecho"
        → 1 substitution in 4 words → WER = 0.25 (25%)
    """

    name = "wer"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 30.0,
        normalize: bool = True,
        language: str = "en"
    ) -> None:
        """Initialize WER metric.

        Args:
            scenario: Scenario with turns containing expected texts
            conversation_manager: Conversation manager with per-turn summaries
            threshold: Maximum acceptable WER (default: 30)
            normalize: Whether to apply text normalization (default: True)
            language: Language code for normalization (default: "en")
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold
        self.normalize = normalize
        self.language = language

    def run(self) -> MetricResult:
        """Calculate WER for all turns with expected texts.

        Returns:
            MetricResult with aggregated WER across all turns
        """
        turns_with_expectations = self.scenario.turns_to_evaluate()

        if not turns_with_expectations:
            return MetricResult(
                metric_name=self.name,
                score=0.0,
                reason="No turns with expected texts to evaluate",
                details={"wer_results": []}
            )

        wer_results = []
        total_errors = 0
        total_reference_words = 0

        for turn in turns_with_expectations:
            # Find matching translated output
            turn_summary = self.conversation_manager.get_turn_summary(turn.id)
            hyp_text = turn_summary.translation_text() if turn_summary else None

            if not hyp_text:
                logger.info(f"No translation found for turn {turn.id}")
                wer_results.append({
                    "id": turn.id,
                    "turn_id": turn.id,
                    "status": "failed",
                    "reason": "No translated text found",
                    "wer": 1.0
                })
                # Count as complete failure
                ref_text = turn.expected_text
                ref_words = _tokenize(ref_text, self.normalize, self.language)
                total_errors += len(ref_words)
                total_reference_words += len(ref_words)
                continue

            # Calculate WER for this pair
            ref_text = turn.expected_text

            result = self._calculate_wer_for_pair(
                turn.id,
                ref_text,
                hyp_text
            )
            wer_results.append(result)

            # Accumulate for overall WER
            total_errors += result["total_errors"]
            total_reference_words += result["reference_words"]

        # Calculate overall WER
        overall_wer = total_errors / total_reference_words if total_reference_words > 0 else 0.0

        # Normalize per-turn results: flatten structure and add score
        per_turn_results = []
        for item in wer_results:
            turn_id = item.get("turn_id")
            wer_value = item.get("wer", 1.0)
            # Convert to 0-100 score (higher is better)
            score_val = max(0.0, 100.0 - (wer_value * 100.0))

            # Flatten all WER fields at turn level (no nested details)
            turn_result = {
                "turn_id": turn_id,
                "score": score_val,
                "status": item.get("status", "evaluated"),
                # WER-specific fields (flattened)
                "wer": item.get("wer"),
                "wer_percentage": item.get("wer_percentage"),
                "substitutions": item.get("substitutions"),
                "deletions": item.get("deletions"),
                "insertions": item.get("insertions"),
                "total_errors": item.get("total_errors"),
                "reference_words": item.get("reference_words"),
                "hypothesis_words": item.get("hypothesis_words"),
                "reference_text": item.get("reference_text"),
                "hypothesis_text": item.get("hypothesis_text"),
                "interpretation": item.get("interpretation"),
                "reason": item.get("reason"),  # For failed turns
            }
            # Remove None values to keep structure clean
            turn_result = {k: v for k, v in turn_result.items() if v is not None}
            per_turn_results.append(turn_result)

        overall_score = max(0.0, 100.0 - (overall_wer * 100.0))

        return MetricResult(
            metric_name=self.name,
            score=overall_score,
            reason=None,
            details={
                "threshold": self.threshold,
                "evaluations": len(wer_results),
                "turns": per_turn_results,
                # WER-specific aggregated fields
                "overall_wer": f"{overall_wer * 100:.2f}%",
                "interpretation": _interpret_wer(overall_wer),
                "total_errors": total_errors,
                "total_reference_words": total_reference_words,
                "normalize": self.normalize,
                "language": self.language
            }
        )

    def _calculate_wer_for_pair(self, expectation_id: str, reference: str, hypothesis: str) -> dict:
        """Calculate WER for a single reference-hypothesis pair.

        Args:
            expectation_id: ID of the expectation
            reference: Reference text (ground truth)
            hypothesis: Hypothesis text (recognized/translated)

        Returns:
            Dictionary with WER calculation details
        """
        # Validate inputs
        if not reference or not reference.strip():
            return {
                "id": expectation_id,
                "turn_id": expectation_id,
                "status": "failed",
                "wer": 1.0,
                "reason": "Reference text is empty",
                "reference_words": 0,
                "total_errors": 0
            }

        if not hypothesis or not hypothesis.strip():
            # Empty recognition = 100% deletion
            ref_words = _tokenize(reference, self.normalize, self.language)
            return {
                "id": expectation_id,
                "turn_id": expectation_id,
                "status": "failed",
                "wer": 1.0,
                "reason": "Hypothesis text is empty",
                "reference_text": reference,
                "hypothesis_text": "",
                "reference_words": len(ref_words),
                "hypothesis_words": 0,
                "substitutions": 0,
                "deletions": len(ref_words),
                "insertions": 0,
                "total_errors": len(ref_words)
            }

        # Tokenize with normalization
        reference_words = _tokenize(reference, self.normalize, self.language)
        hypothesis_words = _tokenize(hypothesis, self.normalize, self.language)

        # Log for debugging
        logger.info(
            f"WER comparison [{expectation_id}] - "
            f"Expected: '{reference}' | "
            f"Translated: '{hypothesis}' | "
            f"Normalized ref: {reference_words} | "
            f"Normalized hyp: {hypothesis_words}"
        )

        # Calculate edit operations
        substitutions, deletions, insertions, total_distance = _calculate_edit_distance(
            reference_words,
            hypothesis_words
        )

        # Calculate WER
        num_reference_words = len(reference_words)
        wer = total_distance / num_reference_words if num_reference_words > 0 else 0.0

        return {
            "id": expectation_id,
            "turn_id": expectation_id,
            "wer": wer,
            "wer_percentage": f"{wer * 100:.2f}%",
            "substitutions": substitutions,
            "deletions": deletions,
            "insertions": insertions,
            "total_errors": total_distance,
            "reference_words": num_reference_words,
            "hypothesis_words": len(hypothesis_words),
            "reference_text": reference,
            "hypothesis_text": hypothesis,
            "interpretation": _interpret_wer(wer)
        }

__all__ = ["WERMetric"]
