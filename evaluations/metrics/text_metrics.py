"""Text-based metrics for translation evaluation."""

import sys
from pathlib import Path

from . import metric, MetricResult

# Add parent directory to path for services import
sys.path.insert(0, str(Path(__file__).parent.parent))


@metric("translation_accuracy")
def translation_accuracy(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """
    Calculate semantic accuracy between expected and recognized text using LLM.

    Uses OpenAI to evaluate how well the recognized text captures
    the semantic meaning of the expected text, even if wording differs.

    Requires AZURE_AI_FOUNDRY_KEY environment variable.
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not recognized or not expected_text:
        return MetricResult(
            metric_name="translation_accuracy",
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
            metric_name="translation_accuracy",
            value=0.0,
            passed=False,
            details={"error": f"Failed to initialize LLM service: {e}"}
        )

    # Define prompts
    system_prompt = """You are an expert evaluator for speech recognition and translation systems.
Assess the semantic similarity between an expected text and a recognized text.

Consider:
- Do they convey the same meaning, even if wording differs?
- Are key facts, names, and numbers preserved?
- How significant are any semantic differences?

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0.0 to 1.0>,
    "reasoning": "<brief explanation in English justifying the score>",
    "key_differences": ["<difference 1>", "<difference 2>"]
}

Scoring guide:
- 1.0: Perfect semantic match (may have minor wording differences)
- 0.9-0.95: Excellent, preserves all key meaning
- 0.8-0.85: Good, minor semantic loss
- 0.7-0.75: Acceptable, some meaning preserved
- 0.5-0.65: Poor, significant meaning lost
- <0.5: Very poor, major semantic differences"""

    user_prompt = f"""Expected text:
"{expected_text}"

Recognized text:
"{recognized}"

Evaluate the semantic similarity."""

    # Make LLM call
    response = llm.call(
        prompt=user_prompt,
        system_prompt=system_prompt,
        response_format="json"
    )

    # Handle API errors
    if not response.success:
        return MetricResult(
            metric_name="translation_accuracy",
            value=0.0,
            passed=False,
            details={"error": response.error}
        )

    # Parse response
    result_data = response.as_json()
    if not result_data:
        return MetricResult(
            metric_name="translation_accuracy",
            value=0.0,
            passed=False,
            details={"error": "Invalid JSON response from LLM"}
        )

    # Extract results
    score = float(result_data.get("score", 0.0))
    reasoning = result_data.get("reasoning", "")
    key_differences = result_data.get("key_differences", [])

    # Pass threshold: 80% semantic similarity
    passed = score >= 0.8

    return MetricResult(
        metric_name="translation_accuracy",
        value=score,
        passed=passed,
        details={
            "method": "llm_semantic",
            "model": llm.model,
            "reasoning": reasoning,
            "key_differences": key_differences,
            "threshold": 0.8,
            "tokens_used": response.tokens_used,
        }
    )
