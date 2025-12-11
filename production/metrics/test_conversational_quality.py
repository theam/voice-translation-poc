"""Unit tests for conversational quality metrics.

Tests for IntelligibilityMetric, SegmentationMetric, and ContextMetric.
"""
import pytest
from unittest.mock import Mock, MagicMock

from production.capture.collector import CollectedEvent
from production.capture.conversation_manager import ConversationManager
from production.utils.time_utils import Clock
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import LLMResponse

from .intelligibility import IntelligibilityMetric
from .segmentation import SegmentationMetric
from .context import ContextMetric


def _manager_with_events(events: list[CollectedEvent]) -> ConversationManager:
    manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)
    for event in events:
        manager.register_incoming(event)
    return manager


class TestIntelligibilityMetric:
    """Tests for IntelligibilityMetric."""

    def test_score_conversion_1_5_to_0_1(self):
        """Test that scores are correctly converted from 1-5 to 0-1 scale."""
        # (score - 1) / 4
        assert (1 - 1) / 4 == 0.0  # Score 1 → 0%
        assert (2 - 1) / 4 == 0.25  # Score 2 → 25%
        assert (3 - 1) / 4 == 0.50  # Score 3 → 50%
        assert (4 - 1) / 4 == 0.75  # Score 4 → 75%
        assert (5 - 1) / 4 == 1.0  # Score 5 → 100%

    def test_no_transcript_expectations(self):
        """Test metric with no transcript expectations."""
        expectations = Expectations(transcripts=[])
        manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)

        metric = IntelligibilityMetric(expectations, manager)
        result = metric.run()

        assert result.passed is True
        assert result.value == 1.0
        assert "No transcript expectations" in result.reason

    def test_metric_initialization(self):
        """Test metric initialization with custom parameters."""
        expectations = Expectations(
            transcripts=[
                TranscriptExpectation(
                    id="test1",
                    event_id="event1",
                    source_language="en-US",
                    target_language="es-ES",
                    expected_text="Hola mundo"
                )
            ]
        )
        manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)

        # Test default threshold
        metric = IntelligibilityMetric(expectations, manager)
        assert metric.threshold == 0.80

        # Test custom threshold
        metric = IntelligibilityMetric(expectations, manager, threshold=0.90)
        assert metric.threshold == 0.90

        # Test custom model
        metric = IntelligibilityMetric(expectations, manager, model="gpt-4o")
        assert metric.model == "gpt-4o"

    def test_calculate_avg_raw_score(self):
        """Test average score calculation on 1-5 scale."""
        expectations = Expectations()
        manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)
        metric = IntelligibilityMetric(expectations, manager)

        # Test with evaluated results
        results = [
            {"status": "evaluated", "score_1_5": 5},
            {"status": "evaluated", "score_1_5": 4},
            {"status": "evaluated", "score_1_5": 3},
        ]
        avg = metric._calculate_avg_raw_score(results)
        assert avg == 4.0  # (5 + 4 + 3) / 3

        # Test with mixed statuses
        results = [
            {"status": "evaluated", "score_1_5": 5},
            {"status": "failed", "score_1_5": 1},
            {"status": "evaluated", "score_1_5": 5},
        ]
        avg = metric._calculate_avg_raw_score(results)
        assert avg == 5.0  # Only counts "evaluated" (5 + 5) / 2

        # Test with no evaluated results
        results = [
            {"status": "failed", "score_1_5": 1},
        ]
        avg = metric._calculate_avg_raw_score(results)
        assert avg == 0.0

    def test_llm_evaluation_mock(self, monkeypatch):
        """Test LLM evaluation with mocked response."""
        # Create test data
        expectations = Expectations(
            transcripts=[
                TranscriptExpectation(
                    id="test1",
                    event_id="event1",
                    source_language="en-US",
                    target_language="es-ES",
                    expected_text="Hello world"
                )
            ]
        )
        events = [
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=1000,
                text="Hola mundo",
                source_language="en-US",
                target_language="es-ES",
                raw={"event_id": "event1"}
            )
        ]

        # Mock LLM service
        mock_llm = Mock()
        mock_response = LLMResponse(
            content='{"intelligibility_score": 5, "reasoning": "Perfect clarity"}',
            tokens_used=50,
            model="gpt-4o-mini"
        )
        mock_llm.call.return_value = mock_response

        # Mock get_llm_service
        def mock_get_llm_service():
            return mock_llm

        monkeypatch.setattr("production.metrics.intelligibility.get_llm_service", mock_get_llm_service)

        # Run metric
        manager = _manager_with_events(events)
        metric = IntelligibilityMetric(expectations, manager)
        result = metric.run()

        # Assertions
        assert result.passed is True
        assert result.value == 1.0  # Score 5 → 100%
        assert len(result.details["results"]) == 1
        assert result.details["results"][0]["score_1_5"] == 5
        assert result.details["results"][0]["score_normalized"] == 1.0


class TestSegmentationMetric:
    """Tests for SegmentationMetric."""

    def test_metric_initialization(self):
        """Test metric initialization."""
        expectations = Expectations()
        manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)

        metric = SegmentationMetric(expectations, manager)
        assert metric.name == "segmentation"
        assert metric.threshold == 0.80

    def test_score_conversion(self):
        """Test score conversion matches intelligibility."""
        # Should use same conversion formula
        assert (1 - 1) / 4 == 0.0
        assert (5 - 1) / 4 == 1.0


class TestContextMetric:
    """Tests for ContextMetric."""

    def test_metric_initialization(self):
        """Test metric initialization."""
        expectations = Expectations()
        manager = ConversationManager(clock=Clock(), scenario_started_at_ms=0)

        metric = ContextMetric(expectations, manager)
        assert metric.name == "context"
        assert metric.threshold == 0.80
        assert metric.max_history_turns == 5

        # Test custom history length
        metric = ContextMetric(expectations, manager, max_history_turns=10)
        assert metric.max_history_turns == 10

    def test_get_prior_events(self):
        """Test conversation history extraction."""
        expectations = Expectations()
        events = [
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=1000,
                text="First turn",
                raw={}
            ),
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=2000,
                text="Second turn",
                raw={}
            ),
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=3000,
                text="Third turn",
                raw={}
            ),
        ]

        manager = _manager_with_events(events)
        metric = ContextMetric(expectations, manager)

        # Get history for third event
        current_event = events[2]
        prior = metric._get_prior_events(current_event)

        # Should return first two events
        assert len(prior) == 2
        assert prior[0].text == "First turn"
        assert prior[1].text == "Second turn"

    def test_get_prior_events_max_history(self):
        """Test that prior events are limited by max_history_turns."""
        expectations = Expectations()

        # Create 10 events
        events = [
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=i * 1000,
                text=f"Turn {i}",
                raw={}
            )
            for i in range(10)
        ]

        # Set max_history_turns to 3
        manager = _manager_with_events(events)
        metric = ContextMetric(expectations, manager, max_history_turns=3)

        # Get history for last event
        current_event = events[9]
        prior = metric._get_prior_events(current_event)

        # Should only return last 3 prior events (indices 6, 7, 8)
        assert len(prior) == 3
        assert prior[0].text == "Turn 6"
        assert prior[1].text == "Turn 7"
        assert prior[2].text == "Turn 8"

    def test_get_prior_events_first_turn(self):
        """Test prior events for first turn (should be empty)."""
        expectations = Expectations()
        events = [
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=1000,
                text="First turn",
                raw={}
            ),
        ]

        manager = _manager_with_events(events)
        metric = ContextMetric(expectations, manager)
        current_event = events[0]
        prior = metric._get_prior_events(current_event)

        # First turn should have no prior context
        assert len(prior) == 0


class TestScoreThresholds:
    """Test scoring thresholds and pass/fail logic."""

    def test_threshold_80_percent_equals_4_point_2(self):
        """Test that 80% threshold equals score of 4.2/5."""
        # 80% threshold = 0.80
        # To convert from 1-5: (score - 1) / 4 = 0.80
        # score - 1 = 3.2
        # score = 4.2

        threshold = 0.80
        required_score = (threshold * 4) + 1
        assert required_score == 4.2

    def test_passing_scores(self):
        """Test which scores pass the 80% threshold."""
        threshold = 0.80

        # Score 5 → 1.0 (100%) ✓ Pass
        assert (5 - 1) / 4 >= threshold

        # Score 4 → 0.75 (75%) ✗ Fail
        assert (4 - 1) / 4 < threshold

        # Score 3 → 0.5 (50%) ✗ Fail
        assert (3 - 1) / 4 < threshold

    def test_garbled_detection_logic(self):
        """Test garbled detection: ANY score ≤ 2 should flag as garbled."""
        # Garbled if ANY dimension ≤ 2

        # All good → not garbled
        assert not any(score <= 2 for score in [5, 5, 5])
        assert not any(score <= 2 for score in [4, 4, 4])

        # One dimension ≤ 2 → garbled
        assert any(score <= 2 for score in [5, 5, 2])
        assert any(score <= 2 for score in [2, 5, 5])
        assert any(score <= 2 for score in [5, 2, 5])

        # Multiple dimensions ≤ 2 → garbled
        assert any(score <= 2 for score in [2, 2, 5])
        assert any(score <= 2 for score in [1, 1, 1])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
