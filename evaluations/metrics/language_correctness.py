"""Language Correctness metric for translation evaluation."""

import sys
from pathlib import Path

from . import metric, MetricResult

# Add parent directory to path for services import
sys.path.insert(0, str(Path(__file__).parent.parent))


@metric("language_correctness")
def language_correctness(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """
    Assess if each sentence in the recognized text is correctly translated.

    In a conversation where speakers use different languages, this metric verifies
    that each sentence in the recognized text matches the language of the corresponding sentence in the expected text.

    This metric does NOT care about semantic content or context - it only checks
    that the language of the recognized text matches the language of the expected text.

    *Example:*
    Expected: I have had a cough since last week, and when I go up stairs I notice that I get short of breath. ¿Has notado sibilancias o algún cambio de color en la flema? Yes, this morning the phlegm was moreyellowish
    Recognized: I've been coughing since last week, and when I go up stairs, I notice I'm short of breath. ¿Has notado sibilancias o algún cambio de color en la flema? Yes, this morning the phlegm was lighter.
    *Result:* Pass
    *Reasoning:* The recognized text is in the same language as the expected text.

    *Example:*
    Expected: Hola, ¿cómo estás?
    Recognized: Hello, how are you?
    *Result:* Pass
    *Reasoning:* The recognized text is in the same language as the expected text.

    *Example:*
    Expected: Hola, ¿cómo estás?
    Recognized: Hola, how are you?
    *Result:* Fail
    *Reasoning:* Part of the recognized text is in the same language as the expected text, but the other part is not.

    *Example:*
    Expected: Hola, ¿cómo estás?
    Recognized: Hola, ¿cómo estás?
    *Result:* Fail
    *Reasoning:* The entire recognized text is in the same language as the expected text.


    Uses OpenAI to split texts into sentences, detect language of each sentence,
    match corresponding sentences, and verify that the language of the recognized text matches the language of the expected text.

    Requires AZURE_AI_FOUNDRY_KEY environment variable.
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not recognized or not expected_text:
        return MetricResult(
            metric_name="language_correctness",
            value=0.0,
            passed=False,
            details={"error": "Missing text for comparison"}
        )

    # Get LLM service
    try:
        from services.llm_service import get_llm_service
        llm = get_llm_service()
    except Exception as e:
        return MetricResult(
            metric_name="language_correctness",
            value=0.0,
            passed=False,
            details={"error": f"Failed to initialize LLM service: {e}"}
        )

    # Define prompts
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

Example case:
Expected: "I have a fever, body aches, and chills. I took 500 miligrams of acetaminophen four hours ago, but it hasn't gone down. Está bien. ¿Has estado cerca de alguien que haya estado enfermo recientemente? Yes. My son had the flu last week."
Recognized: "I have body aches and chills. Four hours ago I took 500 mg of acetaminophen, but it hasn't gone down. Sí, mi hijo tuvo gripe la semana pasada."

Analysis:
- Expected sentence 1 (English): "I have a fever, body aches, and chills. I took 500 miligrams of acetaminophen four hours ago, but it hasn't gone down."
  → Matches recognized sentence 1 (English): "I have body aches and chills. Four hours ago I took 500 mg of acetaminophen, but it hasn't gone down."
  → Languages match (both English) ✓
- Expected sentence 2 (Spanish): "Está bien. ¿Has estado cerca de alguien que haya estado enfermo recientemente?"
  → Missing in recognized (omitted) - skip this pair
- Expected sentence 3 (English): "Yes. My son had the flu last week."
  → Matches recognized sentence 2 (Spanish): "Sí, mi hijo tuvo gripe la semana pasada."
  → Languages DON'T match (English vs Spanish) ✗ FAIL

Result: FAIL
Reason: The expected sentence "Yes. My son had the flu last week" (English) was recognized as "Sí, mi hijo tuvo gripe la semana pasada" (Spanish). The languages don't match.

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
"{expected_text}"

Recognized text:
"{recognized}"

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
        return MetricResult(
            metric_name="language_correctness",
            value=0.0,
            passed=False,
            details={"error": response.error}
        )

    # Parse response
    result_data = response.as_json()
    if not result_data:
        return MetricResult(
            metric_name="language_correctness",
            value=0.0,
            passed=False,
            details={"error": "Invalid JSON response from LLM"}
        )

    # Extract results
    sentence_pairs = result_data.get("sentence_pairs", [])
    score = float(result_data.get("score", 0.0))
    correct_count = int(result_data.get("correct_count", 0))
    total_count = int(result_data.get("total_count", 0))
    missing_count = int(result_data.get("missing_count", 0))
    reasoning = result_data.get("reasoning", "")

    # Pass threshold: 100% of matched sentences must have matching languages (score == 1.0)
    passed = score >= 1.0

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

    return MetricResult(
        metric_name="language_correctness",
        value=score,
        passed=passed,
        details={
            "method": "llm_sentence_level_language_detection",
            "model": llm.model,
            "sentence_pairs": sentence_pairs,
            "correct_count": correct_count,
            "total_count": total_count,
            "missing_count": missing_count,
            "missing_sentences": missing_sentences,
            "issues": issues,
            "reasoning": reasoning,
            "threshold": 1.0,
            "tokens_used": response.tokens_used,
            "recognized_text": recognized,
            "reference_text": expected_text,
        }
    )

