"""Metrics for evaluating translation scenarios."""
from __future__ import annotations

from typing import List

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations

from .base import Metric, MetricResult
from .completeness import CompletenessMetric
from .context import ContextMetric
from .intelligibility import IntelligibilityMetric
from .intent_preservation import IntentPreservationMetric
from .language_correctness import LanguageCorrectnessMetric
from .runner import MetricsRunner, MetricsSummary
from .segmentation import SegmentationMetric
from .sequence import SequenceMetric
from .technical_terms import TechnicalTermsMetric
from .wer import WERMetric


def get_metrics(expectations: Expectations, conversation_manager: ConversationManager) -> List[Metric]:
    return [
        SequenceMetric(expectations, conversation_manager),
        WERMetric(expectations, conversation_manager),  # WER with default threshold 0.3
        TechnicalTermsMetric(expectations, conversation_manager),  # Technical terms with default threshold 0.90
        CompletenessMetric(expectations, conversation_manager),  # Completeness with default threshold 0.85
        IntentPreservationMetric(expectations, conversation_manager),  # Intent preservation with default threshold 0.85
        LanguageCorrectnessMetric(expectations, conversation_manager),  # Language correctness with default threshold 1.0
        IntelligibilityMetric(expectations, conversation_manager),  # Intelligibility with default threshold 0.80
        SegmentationMetric(expectations, conversation_manager),  # Segmentation with default threshold 0.80
        ContextMetric(expectations, conversation_manager),  # Context with default threshold 0.80
    ]
    """Instantiate all metrics for a run.

    Available metrics:
    - SequenceMetric: Validates event ordering
    - WERMetric: Calculates Word Error Rate for translation accuracy
    - TechnicalTermsMetric: Evaluates technical term preservation using LLM
    - CompletenessMetric: Evaluates information completeness using LLM
    - IntentPreservationMetric: Evaluates communicative intent preservation using LLM
    - LanguageCorrectnessMetric: Verifies sentence-level language matching using LLM
    - IntelligibilityMetric: Evaluates text clarity and readability using LLM (1-5 scale)
    - SegmentationMetric: Evaluates sentence boundaries and turn segmentation using LLM (1-5 scale)
    - ContextMetric: Evaluates conversational context and relevance using LLM (1-5 scale)

    Args:
        expectations: Scenario expectations (transcripts, sequence, etc.)
        conversation_manager: Conversation manager with per-turn summaries

    Returns:
        List of instantiated metric objects ready to run
    """


__all__ = [
    "Metric",
    "MetricResult",
    "MetricsSummary",
    "MetricsRunner",
    "get_metrics",
    "SequenceMetric",
    "TechnicalTermsMetric",
    "WERMetric",
    "CompletenessMetric",
    "IntentPreservationMetric",
    "LanguageCorrectnessMetric",
    "IntelligibilityMetric",
    "SegmentationMetric",
    "ContextMetric",
]
