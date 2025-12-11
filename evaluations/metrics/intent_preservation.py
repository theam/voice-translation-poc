"""Intent Preservation metric for translation evaluation."""

import sys
from pathlib import Path

from . import metric, MetricResult

# Add parent directory to path for services import
sys.path.insert(0, str(Path(__file__).parent.parent))


@metric("intent_preservation")
def intent_preservation(input_audio: Path, expected_text: str, received_data: dict) -> MetricResult:
    """
    Calculate how well the communicative intent is preserved in translation.

    Uses OpenAI to evaluate whether the speaker's intended message, purpose,
    and communicative goals are maintained in the recognized/translated text.

    Requires AZURE_AI_FOUNDRY_KEY environment variable.
    """
    recognized = received_data.get("recognized_text", "")

    # Validate inputs
    if not recognized or not expected_text:
        return MetricResult(
            metric_name="intent_preservation",
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
            metric_name="intent_preservation",
            value=0.0,
            passed=False,
            details={"error": f"Failed to initialize LLM service: {e}"}
        )

    # Define prompts
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
"{expected_text}"

Recognized text:
"{recognized}"

Evaluate whether the communicative intent is preserved."""

    # Make LLM call
    response = llm.call(
        prompt=user_prompt,
        system_prompt=system_prompt,
        response_format="json"
    )

    # Handle API errors
    if not response.success:
        return MetricResult(
            metric_name="intent_preservation",
            value=0.0,
            passed=False,
            details={"error": response.error}
        )

    # Parse response
    result_data = response.as_json()
    if not result_data:
        return MetricResult(
            metric_name="intent_preservation",
            value=0.0,
            passed=False,
            details={"error": "Invalid JSON response from LLM"}
        )

    # Extract results
    score = float(result_data.get("score", 0.0))
    reasoning = result_data.get("reasoning", "")
    expected_intent = result_data.get("expected_intent", "")
    recognized_intent = result_data.get("recognized_intent", "")
    intent_type = result_data.get("intent_type", "unknown")
    tone_match = result_data.get("tone_match", False)
    pragmatic_issues = result_data.get("pragmatic_issues", [])

    # Pass threshold: 85% intent preservation
    passed = score >= 0.85

    return MetricResult(
        metric_name="intent_preservation",
        value=score,
        passed=passed,
        details={
            "method": "llm_intent",
            "model": llm.model,
            "reasoning": reasoning,
            "expected_intent": expected_intent,
            "recognized_intent": recognized_intent,
            "intent_type": intent_type,
            "tone_match": tone_match,
            "pragmatic_issues": pragmatic_issues,
            "threshold": 0.85,
            "tokens_used": response.tokens_used,
            "recognized_text": recognized,
            "reference_text": expected_text,
        }
    )
