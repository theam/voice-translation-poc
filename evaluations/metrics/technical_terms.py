"""Technical Term Accuracy metric for translation evaluation."""

import sys
from pathlib import Path

from . import metric, MetricResult

# Add parent directory to path for services import
sys.path.insert(0, str(Path(__file__).parent.parent))


@metric("technical_term_accuracy")
def technical_term_accuracy(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """
    Calculate accuracy of technical terms, proper nouns, and specialized vocabulary.

    Uses OpenAI to identify and evaluate whether technical terms, proper names,
    acronyms, and domain-specific vocabulary are correctly translated/preserved.

    Requires AZURE_AI_FOUNDRY_KEY environment variable.
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not recognized or not expected_text:
        return MetricResult(
            metric_name="technical_term_accuracy",
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
            metric_name="technical_term_accuracy",
            value=0.0,
            passed=False,
            details={"error": f"Failed to initialize LLM service: {e}"}
        )

    # Define prompts
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
"{expected_text}"

Recognized text:
"{recognized}"

Identify and evaluate all technical terms, proper nouns, and specialized vocabulary."""

    # Make LLM call
    response = llm.call(
        prompt=user_prompt,
        system_prompt=system_prompt,
        response_format="json"
    )

    # Handle API errors
    if not response.success:
        return MetricResult(
            metric_name="technical_term_accuracy",
            value=0.0,
            passed=False,
            details={"error": response.error}
        )

    # Parse response
    result_data = response.as_json()
    if not result_data:
        return MetricResult(
            metric_name="technical_term_accuracy",
            value=0.0,
            passed=False,
            details={"error": "Invalid JSON response from LLM"}
        )

    # Extract results
    score = float(result_data.get("score", 0.0))
    reasoning = result_data.get("reasoning", "")
    technical_terms_found = result_data.get("technical_terms_found", [])
    correct_terms = result_data.get("correct_terms", [])
    incorrect_terms = result_data.get("incorrect_terms", [])
    has_technical_content = result_data.get("has_technical_content", True)

    # Pass threshold: 90% for technical terms (higher bar than general text)
    passed = score >= 0.90

    return MetricResult(
        metric_name="technical_term_accuracy",
        value=score,
        passed=passed,
        details={
            "method": "llm_technical_terms",
            "model": llm.model,
            "reasoning": reasoning,
            "technical_terms_found": technical_terms_found,
            "correct_terms": correct_terms,
            "incorrect_terms": incorrect_terms,
            "has_technical_content": has_technical_content,
            "threshold": 0.90,
            "tokens_used": response.tokens_used,
            "recognized_text": recognized,
            "reference_text": expected_text,
        }
    )
