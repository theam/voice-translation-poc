"""Context metric for conversational quality evaluation.

Evaluates whether responses maintain conversational context and relevance.
Uses LLM evaluation with conversation history to score context awareness
on a 1-5 scale, converted to 0-100%.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from production.capture.conversation_manager import ConversationManager, TurnSummary
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import LLMService, get_llm_service

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


class ContextMetric(Metric):
    """Evaluate conversational context and relevance.

    Uses LLM (OpenAI) to assess whether the response maintains conversational
    context, stays on topic, and is relevant to the conversation. Requires
    conversation history for accurate evaluation. Scores on a 1-5 scale,
    converted to 0-100%.

    The metric:
    1. Extracts translated text from collected events
    2. Gathers conversation history (prior turns)
    3. Uses LLM to evaluate context awareness and relevance
    4. Converts 1-5 score to 0-100% scale: (score - 1) / 4 * 100
    5. Returns pass/fail based on 80% threshold (score of 4.2/5)

    Scoring guide (1-5):
        5: Perfect context awareness, fully relevant to conversation
        4: Good context, minor deviation but still relevant
        3: Acceptable context, some drift but topic maintained
        2: Poor context, significant drift or topic change (e.g., UTI question)
        1: Complete context loss, unrelated or nonsensical response

    Example (Good Context):
        Prior: "I have a fever and body aches."
        Current: "Have you been near anyone sick recently?"
        → Score: 5/5 (100%) - Relevant follow-up question

    Example (Context Loss - UTI):
        Prior: "I have a fever and body aches."
        Current: "Do you have any urinary tract infection symptoms?"
        → Score: 2/5 (25%) - Topic change, poor context

    Example (Hallucination Drift - Paddle→Soccer):
        Prior: "My son plays paddle."
        Current: "That's great! Soccer is good exercise."
        → Score: 3/5 (50%) - Related but incorrect sport
    """

    name = "context"

    def __init__(
        self,
        expectations: Expectations,
        conversation_manager: ConversationManager,
        threshold: float = 0.80,
        model: Optional[str] = None
    ) -> None:
        """Initialize context metric.

        Args:
            expectations: Scenario expectations with reference texts
            conversation_manager: Conversation manager with per-turn summaries
            threshold: Minimum score to pass (default: 0.80 = 80% = 4.2/5)
            model: Optional LLM model override (default: from config)
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self.threshold = threshold
        self.model = model

    def run(self) -> MetricResult:
        """Evaluate context for all transcript expectations.

        Returns:
            MetricResult with overall context score
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
            llm = get_llm_service() if not self.model else LLMService(model=self.model)
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
                total_score += result["score_normalized"]
                evaluations += 1

        # Calculate overall score (0-1 scale)
        overall_score = total_score / evaluations if evaluations > 0 else 0.0
        passed = overall_score >= self.threshold

        # Calculate average on 1-5 scale for reporting
        avg_score_1_5 = self._calculate_avg_raw_score(results)

        return MetricResult(
            metric_name=self.name,
            passed=passed,
            value=overall_score,
            reason=None if passed else f"Context {overall_score:.2%} below threshold {self.threshold:.0%}",
            details={
                "overall_score": f"{overall_score * 100:.2f}%",
                "threshold": self.threshold,
                "evaluations": evaluations,
                "results": results,
                # Session aggregates
                "avg_context_1_5": avg_score_1_5,
                "avg_context_0_100": overall_score * 100
            }
        )

    def _evaluate_expectation(self, expectation: TranscriptExpectation, llm) -> dict:
        """Evaluate context for a single transcript expectation.

        Args:
            expectation: Transcript expectation with event ID
            llm: LLM service instance

        Returns:
            Dictionary with evaluation results
        """
        # Find matching event
        turn = self.conversation_manager.get_turn_summary(expectation.event_id)
        hypothesis_text = turn.translation_text() if turn else None
        if not hypothesis_text:
            return {
                "id": expectation.id,
                "event_id": expectation.event_id,
                "status": "failed",
                "reason": "No translated text found",
                "score_1_5": 1,
                "score_normalized": 0.0
            }

        # Get conversation history (prior turns) by iterating through turns
        current_turn = None
        prior_turns = []
        for turn in self.conversation_manager.iter_turns():
            # Stop when we reach the current turn
            if turn.turn_id == expectation.event_id:
                current_turn = turn
                break
            # Add turn to history if it has translation text
            prior_turns.append(turn)

        # Call LLM to evaluate context
        llm_result = self._call_llm_evaluation_with_context(
            current_turn=current_turn,
            prior_turns=prior_turns,
            llm=llm
        )

        if not llm_result["success"]:
            return {
                "id": expectation.id,
                "event_id": expectation.event_id,
                "status": "error",
                "reason": llm_result["error"],
                "score_1_5": 1,
                "score_normalized": 0.0
            }

        # Convert 1-5 to 0-1 scale: (score - 1) / 4
        score_1_5 = llm_result["context_score"]
        score_normalized = (score_1_5 - 1) / 4

        return {
            "id": expectation.id,
            "event_id": expectation.event_id,
            "status": "evaluated",
            "score_1_5": score_1_5,
            "score_normalized": score_normalized,
            "score_percentage": f"{score_normalized * 100:.2f}%",
            "passed": score_normalized >= self.threshold,
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

Score from 1-5:
- 5: Perfect context awareness, fully relevant to conversation history
- 4: Good context, minor deviation but still relevant to the topic
- 3: Acceptable context, some drift but topic generally maintained
- 2: Poor context, significant drift or topic change (e.g., asking about unrelated symptoms)
- 1: Complete context loss, unrelated or nonsensical response

Consider:
- Does the response relate to what was just said?
- Is it a logical follow-up or continuation?
- Does it stay on topic or introduce unrelated information?
- Is there any hallucination or drift (e.g., confusing sports like paddle→soccer)?

IMPORTANT: All responses must be in English, including the reasoning field.

Respond ONLY with valid JSON:
{
    "context_score": <integer 1-5>,
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

Evaluate the context (relevance to conversation history) on a scale of 1-5."""

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
        score = result_data.get("context_score", 1)
        if not isinstance(score, int) or not (1 <= score <= 5):
            logger.warning(f"Invalid context score from LLM: {score}, defaulting to 1")
            score = 1

        return {
            "success": True,
            "context_score": score,
            "reasoning": result_data.get("reasoning", ""),
            "tokens_used": response.tokens_used,
            "model": response.model
        }

    def _calculate_avg_raw_score(self, results: list) -> float:
        """Calculate average score on 1-5 scale.

        Args:
            results: List of evaluation results

        Returns:
            Average score (1-5 scale)
        """
        evaluated = [r for r in results if r["status"] == "evaluated"]
        if not evaluated:
            return 0.0

        total = sum(r["score_1_5"] for r in evaluated)
        return round(total / len(evaluated), 2)


__all__ = ["ContextMetric"]
