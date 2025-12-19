"""Metrics for evaluating translation scenarios."""
from __future__ import annotations

from typing import List

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario

from .base import Metric, MetricResult
from .completeness import CompletenessMetric
from .context import ContextMetric
from .intelligibility import IntelligibilityMetric
from .intent_preservation import IntentPreservationMetric
from .overlap import OverlapMetric
from .target_language import TargetLanguageMetric
from .runner import MetricsRunner, MetricsSummary
from .segmentation import SegmentationMetric
from .technical_terms import TechnicalTermsMetric
from .wer import WERMetric


# Metric registry mapping metric names to classes
METRIC_REGISTRY = {
    "intelligibility": IntelligibilityMetric,
    "segmentation": SegmentationMetric,
    "context": ContextMetric,
    "wer": WERMetric,
    "technical_terms": TechnicalTermsMetric,
    "completeness": CompletenessMetric,
    "intent_preservation": IntentPreservationMetric,
    "target_language": TargetLanguageMetric,
    "overlap": OverlapMetric,
}


def create_metric(
    name: str,
    scenario: Scenario,
    conversation_manager: ConversationManager,
    model: str | None = None,
    **kwargs
) -> Metric:
    """Create a metric instance by name.

    Factory method for creating metric instances with standardized parameters.

    Args:
        name: Metric name (e.g., "intelligibility", "context", "wer")
        scenario: Scenario definition with turns/expected text
        conversation_manager: Conversation manager with per-turn summaries
        model: Optional LLM model override for LLM-based metrics
        **kwargs: Additional metric-specific parameters (e.g., threshold)

    Returns:
        Instantiated metric instance

    Raises:
        ValueError: If metric name is not recognized

    Example:
        >>> metric = create_metric("intelligibility", scenario, conv_mgr, model="gpt-4")
        >>> result = metric.run()
    """
    metric_class = METRIC_REGISTRY.get(name)
    if not metric_class:
        available = ", ".join(sorted(METRIC_REGISTRY.keys()))
        raise ValueError(f"Unknown metric '{name}'. Available: {available}")

    # Build kwargs for metric initialization
    init_kwargs = {"scenario": scenario, "conversation_manager": conversation_manager}

    # Add model parameter if provided and metric supports it
    if model is not None:
        init_kwargs["model"] = model

    # Add any additional kwargs (e.g., threshold)
    init_kwargs.update(kwargs)

    return metric_class(**init_kwargs)


def get_metrics(scenario: Scenario, conversation_manager: ConversationManager) -> List[Metric]:
    """Instantiate metrics for a run.

    If scenario.metrics is empty, instantiates all available metrics.
    If scenario.metrics is specified, only instantiates those metrics.

    Available metrics:
    - wer: Calculates Word Error Rate for translation accuracy
    - technical_terms: Evaluates technical term preservation using LLM
    - completeness: Evaluates information completeness using LLM
    - intent_preservation: Evaluates communicative intent preservation using LLM
    - target_language: Verifies translated text matches expected target language per turn using LLM
    - intelligibility: Evaluates text clarity and readability using LLM (1-5 scale)
    - segmentation: Evaluates sentence boundaries and turn segmentation using LLM (1-5 scale)
    - context: Evaluates conversational context and relevance using LLM (1-5 scale)
    - overlap: Detects audio overlap (response arriving during transmission)

    Args:
        scenario: Scenario with turns containing expectations
        conversation_manager: Conversation manager with per-turn summaries

    Returns:
        List of instantiated metric objects ready to run

    Example:
        # Run all metrics (default)
        scenario = Scenario(...)
        metrics = get_metrics(scenario, conv_mgr)

        # Run only specific metrics (e.g., for calibration)
        scenario = Scenario(..., metrics=["intelligibility"])
        metrics = get_metrics(scenario, conv_mgr)
    """
    # If no specific metrics requested, return all metrics
    if not scenario.metrics:
        return [
            WERMetric(scenario, conversation_manager),  # WER with default threshold 0.3
            TechnicalTermsMetric(scenario, conversation_manager),  # Technical terms with default threshold 0.90
            CompletenessMetric(scenario, conversation_manager),  # Completeness with default threshold 0.85
            IntentPreservationMetric(scenario, conversation_manager),  # Intent preservation with default threshold 0.85
            IntelligibilityMetric(scenario, conversation_manager),  # Intelligibility with default threshold 0.80
            SegmentationMetric(scenario, conversation_manager),  # Segmentation with default threshold 0.80
            TargetLanguageMetric(scenario, conversation_manager),  # Target language validation per turn
            ContextMetric(scenario, conversation_manager),  # Context with default threshold 0.80
            OverlapMetric(scenario, conversation_manager),  # Audio overlap detection
        ]

    # Return only requested metrics
    return [
        create_metric(metric_name, scenario, conversation_manager)
        for metric_name in scenario.metrics
    ]


__all__ = [
    "Metric",
    "MetricResult",
    "MetricsSummary",
    "MetricsRunner",
    "get_metrics",
    "create_metric",
    "METRIC_REGISTRY",
    "TechnicalTermsMetric",
    "WERMetric",
    "CompletenessMetric",
    "IntentPreservationMetric",
    "LanguageCorrectnessMetric",
    "IntelligibilityMetric",
    "SegmentationMetric",
    "ContextMetric",
    "OverlapMetric",
]
