"""Word Error Rate (WER) metric for ASR accuracy evaluation.

WER measures the accuracy of Automatic Speech Recognition (ASR) by comparing
the recognized text against a reference transcription.

Formula: WER = (S + D + I) / N
Where:
    S = Substitutions (words replaced)
    D = Deletions (words removed)
    I = Insertions (words added)
    N = Number of words in reference
"""

from pathlib import Path
from typing import Dict, Any, Tuple, List

from . import metric, MetricResult
from .text_normalization import normalize_text_for_wer


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


@metric("wer")
def word_error_rate(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """Calculate Word Error Rate (WER) for ASR accuracy.

    WER measures the percentage of words that were incorrectly recognized
    compared to the reference transcription. It's the standard metric for
    evaluating ASR systems.

    Args:
        input_audio: Path to audio file (not used, kept for interface consistency)
        expected_text: Reference transcription (ground truth)
        received_data: Dictionary containing "recognized_text" key with ASR output

    Returns:
        MetricResult with WER value (0.0 = perfect, 1.0+ = worse than empty output)

    Example:
        Reference: "tengo dolor de pecho"
        ASR: "tengo color de pecho"
        → 1 substitution in 4 words → WER = 0.25 (25%)
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not expected_text or not expected_text.strip():
        return MetricResult(
            metric_name="wer",
            value=1.0,
            passed=False,
            details={"error": "Expected text is empty or missing"}
        )

    if not recognized or not recognized.strip():
        # Empty recognition = 100% deletion
        ref_words = _tokenize(expected_text)
        return MetricResult(
            metric_name="wer",
            value=1.0,
            passed=False,
            details={
                "error": "Recognized text is empty",
                "reference_words": len(ref_words),
                "substitutions": 0,
                "deletions": len(ref_words),
                "insertions": 0,
                "reference_text": expected_text,
                "recognized_text": ""
            }
        )

    # Tokenize into words with normalization (expands contractions)
    # This makes WER more robust to variations like "I've" vs "I have"
    reference_words = _tokenize(expected_text, normalize=True, language="en")
    hypothesis_words = _tokenize(recognized, normalize=True, language="en")

    # Calculate edit operations
    substitutions, deletions, insertions, total_distance = _calculate_edit_distance(
        reference_words,
        hypothesis_words
    )

    # Calculate WER
    num_reference_words = len(reference_words)
    wer = total_distance / num_reference_words if num_reference_words > 0 else 0.0

    # WER can exceed 1.0 if there are many insertions
    # For example, if reference has 4 words but hypothesis has 10 incorrect words
    # Pass threshold: WER <= 0.3 (30% error rate is acceptable for many use cases)
    passed = wer <= 0.3

    return MetricResult(
        metric_name="wer",
        value=wer,
        passed=passed,
        details={
            "wer_percentage": f"{wer * 100:.2f}%",
            "substitutions": substitutions,
            "deletions": deletions,
            "insertions": insertions,
            "total_errors": total_distance,
            "reference_words": num_reference_words,
            "hypothesis_words": len(hypothesis_words),
            "reference_text": expected_text,
            "recognized_text": recognized,
            "normalized": True,  # Indicates contraction expansion was applied
            "threshold": 0.3,
            "interpretation": _interpret_wer(wer)
        }
    )


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
