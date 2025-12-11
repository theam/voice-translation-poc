"""Completeness Score metric for translation evaluation."""

import sys
from pathlib import Path

from . import metric, MetricResult

# Add parent directory to path for services import
sys.path.insert(0, str(Path(__file__).parent.parent))


@metric("completeness_score")
def completeness_score(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """
    Calculate completeness of translation - ensures all information is preserved.

    Uses OpenAI to evaluate whether the recognized text contains all the
    information present in the expected text, without omissions or additions.

    Requires AZURE_AI_FOUNDRY_KEY environment variable.
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not recognized or not expected_text:
        return MetricResult(
            metric_name="completeness_score",
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
            metric_name="completeness_score",
            value=0.0,
            passed=False,
            details={"error": f"Failed to initialize LLM service: {e}"}
        )

    # Define prompts
    system_prompt = """You are an expert evaluator for translation completeness.
Assess whether the recognized text contains ALL information from the expected text.

Consider:
- Are there any omissions (information in expected but missing in recognized)?
- Are there any additions (extra information not in expected)?
- Are all key facts, names, numbers, and details preserved?
- Is the information density comparable?
- If you find that there are missing sentences in the translation, that should dramatically reduce the score, even if it doesn't affect the overall meaning.

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0.0 to 1.0>,
    "reasoning": "<detailed explanation in English of what's complete, missing, or added>",
    "omissions": ["<missing element 1>", "<missing element 2>"],
    "additions": ["<extra element 1>", "<extra element 2>"]
}

Scoring guide:
- 1.0: Perfect - all information preserved, nothing missing or added
- 0.9-0.95: Excellent - minor detail missing or slight rephrasing
- 0.8-0.85: Good - one small element missing or added
- 0.7-0.75: Acceptable - some information missing but core preserved
- 0.5-0.65: Poor - significant omissions or additions
- <0.5: Very poor - major information loss or distortion"""

    user_prompt = f"""Expected text:
"{expected_text}"

Recognized text:
"{recognized}"

Evaluate the completeness of the recognized text."""

    # Make LLM call
    response = llm.call(
        prompt=user_prompt,
        system_prompt=system_prompt,
        response_format="json"
    )

    # Handle API errors
    if not response.success:
        return MetricResult(
            metric_name="completeness_score",
            value=0.0,
            passed=False,
            details={"error": response.error}
        )

    # Parse response
    result_data = response.as_json()
    if not result_data:
        return MetricResult(
            metric_name="completeness_score",
            value=0.0,
            passed=False,
            details={"error": "Invalid JSON response from LLM"}
        )

    # Extract results
    score = float(result_data.get("score", 0.0))
    reasoning = result_data.get("reasoning", "")
    omissions = result_data.get("omissions", [])
    additions = result_data.get("additions", [])

    # Pass threshold: 85% completeness
    passed = score >= 0.85

    return MetricResult(
        metric_name="completeness_score",
        value=score,
        passed=passed,
        details={
            "method": "llm_completeness",
            "model": llm.model,
            "reasoning": reasoning,
            "omissions": omissions,
            "additions": additions,
            "threshold": 0.85,
            "tokens_used": response.tokens_used,
            "recognized_text": recognized,
            "reference_text": expected_text,
        }
    )
