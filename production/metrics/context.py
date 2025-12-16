"""Context metric for conversational quality evaluation.

Evaluates whether responses maintain conversational context and relevance.
Uses LLM evaluation with conversation history to score context awareness
on a 0-100 scale (0 = complete context loss, 100 = perfect context).
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from production.capture.conversation_manager import ConversationManager, TurnSummary
from production.scenario_engine.models import Scenario, ScenarioTurn
from production.services.llm_service import LLMService, get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class ContextMetric(Metric):
    """Evaluate conversational context and relevance.

    Uses LLM (OpenAI) to assess whether the final response maintains conversational
    context, stays on topic, and is relevant to the conversation history. Evaluates
    only the last turn using all previous turns as context. Scores on a 0-100 scale.

    The metric:
    1. Identifies the last turn with expected text
    2. Gathers all previous turns as conversation history
    3. Uses LLM to evaluate how well the last turn maintains context
    4. Returns pass/fail based on 80 threshold

    Note: Only the last turn is evaluated. This makes sense for context evaluation
    since context is about maintaining conversational flow at the current point,
    given all prior history.

    Scoring guide (0-100 scale):
        100: Perfect context awareness, fully relevant to conversation
        75-99: Good context, minor deviation but still relevant
        50-74: Acceptable context, some drift but topic maintained
        25-49: Poor context, significant drift or topic change (e.g., UTI question)
        0-24: Complete context loss, unrelated or nonsensical response

    Example (Good Context):
        Prior: "I have a fever and body aches."
        Current: "Have you been near anyone sick recently?"
        → Score: 1.0 - Relevant follow-up question

    Example (Context Loss - UTI):
        Prior: "I have a fever and body aches."
        Current: "Do you have any urinary tract infection symptoms?"
        → Score: 0.25 - Topic change, poor context

    Example (Hallucination Drift - Paddle→Soccer):
        Prior: "My son plays paddle."
        Current: "That's great! Soccer is good exercise."
        → Score: 0.50 - Related but incorrect sport
    """

    name = "context"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 80.0,
        model: Optional[str] = None
    ) -> None:
        """Initialize context metric.

        Args:
            expectations: Scenario expectations with reference texts
            conversation_manager: Conversation manager with per-turn summaries
            threshold: Minimum score to pass (default: 80 on 0-100 scale)
            model: Optional LLM model override (default: from config)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold
        self.model = model

    def run(self) -> MetricResult:
        """Evaluate context for the last turn with expected text.

        Returns:
            MetricResult with context score for the last turn
        """
        turns_with_expectations = self.scenario.turns_to_evaluate()

        if not turns_with_expectations:
            return MetricResult(
                metric_name=self.name,
                score=100.0,
                reason="No transcript expectations to evaluate",
                details={"conversation": None}
            )

        # Only evaluate the LAST turn - context is about maintaining flow at the current point
        last_turn = turns_with_expectations[-1]

        # Initialize LLM service
        try:
            llm = get_llm_service() if not self.model else LLMService(model=self.model)
        except Exception as e:
            return MetricResult(
                metric_name=self.name,
                score=0.0,
                reason=f"Failed to initialize LLM service: {e}",
                details={"error": str(e)}
            )

        # Evaluate the last turn
        result = self._evaluate_expectation(last_turn, llm)

        # Extract score from result (0-100)
        if result["status"] == "evaluated":
            score = result["score"]
        else:
            score = 0.0

        # Flatten conversation structure
        conversation_data = {
            "score": score,
            "expected_score": self.scenario.expected_score,
            "status": result["status"],
            # Add all other fields from result (except status which we already have)
            **{k: v for k, v in result.items() if k not in ["status", "score"]}
        }

        return MetricResult(
            metric_name=self.name,
            score=score,
            details={
                "threshold": self.threshold,
                "conversation": conversation_data,
            }
        )

    def _evaluate_expectation(self, turn: ScenarioTurn, llm) -> dict:
        """Evaluate context for a single transcript expectation.

        Args:
            turn: Scenario turn with expected text
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Find matching event
        turn_summary = self.conversation_manager.get_turn_summary(turn.id)
        hypothesis_text = turn_summary.translation_text() if turn_summary else None
        if not hypothesis_text:
            return {
                "id": turn.id,
                "turn_id": turn.id,
                "status": "failed",
                "reason": "No translated text found",
                "score": 0.0
            }

        # Get conversation history (prior turns) by iterating through turns
        current_turn = None
        prior_turns = []
        for summary in self.conversation_manager.iter_turns():
            # Stop when we reach the current turn
            if summary.turn_id == turn.id:
                current_turn = summary
                break
            # Add turn to history if it has translation text
            prior_turns.append(summary)

        # Call LLM to evaluate context
        llm_result = self._call_llm_evaluation_with_context(
            current_turn=current_turn,
            prior_turns=prior_turns,
            llm=llm
        )

        if not llm_result["success"]:
            return {
                "id": turn.id,
                "turn_id": turn.id,
                "status": "error",
                "reason": llm_result["error"],
                "score": 0.0
            }

        # LLM returns 0-100
        score = llm_result["score"]

        return {
            "id": turn.id,
            "turn_id": turn.id,
            "status": "evaluated",
            "score": score,
            "reasoning": llm_result["reasoning"],
            "text": hypothesis_text,
            "context_length": len(prior_turns),
            "tokens_used": llm_result["tokens_used"],
            "model": llm_result["model"]
        }

    def _call_llm_evaluation_with_context(
        self,
        current_turn: TurnSummary,
        prior_turns: List[TurnSummary],
        llm
    ) -> dict:
        """Call LLM to evaluate context with conversation history.

        Args:
            current_turn: Current turn being evaluated
            prior_turns: List of prior conversation turns
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        system_prompt = """You are an expert evaluator for conversational quality.
Evaluate the CONTEXT of the current response in relation to the conversation history.

Context measures whether the response maintains conversational context, stays on topic,
and is relevant to what was previously discussed.

Score from 0 to 100:
- 100: Perfect context awareness, fully relevant to conversation history
- 75-99: Good context, minor deviation but still relevant to the topic
- 50-74: Acceptable context, some drift but topic generally maintained
- 25-49: Poor context, significant drift or topic change (e.g., asking about unrelated symptoms)
- 0-24: Complete context loss, unrelated or nonsensical response

Consider:
- Does the response relate to what was just said?
- Is it a logical follow-up or continuation?
- Does it stay on topic or introduce unrelated information?
- Is there any hallucination or drift (e.g., confusing sports like paddle→soccer)?

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "score": <float 0-100>,
    "reasoning": "<brief explanation in English of the context assessment>"
}"""

        # Build conversation history string from turns
        if prior_turns:
            history_lines = []
            for turn in prior_turns:
                # Use turn_id as speaker identifier
                speaker = turn.turn_id
                text = turn.translation_text()
                if text:
                    history_lines.append(f"{speaker}: \"{text}\"")
            history_str = "\n".join(history_lines)
        else:
            history_str = "(No prior conversation history - this is the first turn)"

        current_text = current_turn.translation_text()
        user_prompt = f"""Conversation history:
{history_str}

Current response:
"{current_text}"

Evaluate the context (relevance to conversation history) on a scale of 0 to 100."""

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

        # Extract and validate score
        score = float(result_data.get("score", 0.0))
        if not isinstance(score, (int, float)) or not (0.0 <= score <= 100.0):
            logger.warning(f"Invalid context score from LLM: {score}, defaulting to 0.0")
            score = 0.0

        return {
            "success": True,
            "score": score,
            "reasoning": result_data.get("reasoning", ""),
            "tokens_used": response.tokens_used,
            "model": response.model
        }


__all__ = ["ContextMetric"]
