"""Quick validation test for BargeInMetric implementation.

This script validates the barge-in metric can be instantiated and
its structure is correct. It doesn't run a full test scenario.
"""
from production.metrics import BargeInMetric, create_metric, METRIC_REGISTRY
from production.scenario_engine.models import Scenario, Participant, ScenarioTurn


def test_metric_registration():
    """Test that BargeInMetric is registered."""
    assert "barge_in" in METRIC_REGISTRY
    assert METRIC_REGISTRY["barge_in"] == BargeInMetric
    print("✅ BargeInMetric is registered in METRIC_REGISTRY")


def test_metric_attributes():
    """Test that BargeInMetric has required attributes."""
    assert hasattr(BargeInMetric, "name")
    assert BargeInMetric.name == "barge_in"
    print("✅ BargeInMetric has correct name attribute")


def test_metric_methods():
    """Test that BargeInMetric has required methods."""
    assert hasattr(BargeInMetric, "run")
    assert hasattr(BargeInMetric, "_find_barge_in_turns")
    assert hasattr(BargeInMetric, "_calculate_cutoff_latency")
    assert hasattr(BargeInMetric, "_detect_content_mixing")
    assert hasattr(BargeInMetric, "_calculate_barge_in_score")
    print("✅ BargeInMetric has all required methods")


def test_no_barge_in_scenario():
    """Test metric behavior when no barge-in turns exist."""
    from production.capture.conversation_manager import ConversationManager
    from production.utils.time_utils import Clock

    # Create a simple scenario without barge-in
    scenario = Scenario(
        id="test_no_barge_in",
        description="Test scenario without barge-in",
        participants={
            "patient": Participant(
                name="patient",
                source_language="es",
                target_language="en"
            )
        },
        turns=[
            ScenarioTurn(
                id="turn1",
                type="play_audio",
                participant="patient",
                barge_in=False  # No barge-in
            )
        ]
    )

    clock = Clock(acceleration=1.0)
    conv_manager = ConversationManager(clock=clock, scenario_started_at_ms=0)

    # Create and run metric
    metric = BargeInMetric(scenario, conv_manager)
    result = metric.run()

    # Verify result structure
    assert result.metric_name == "barge_in"
    assert result.score is None
    assert "No barge-in turns found" in result.reason
    assert "turns" in result.details
    assert len(result.details["turns"]) == 0

    print("✅ BargeInMetric correctly handles scenario with no barge-in turns")
    print(f"   Result: {result.reason}")


def test_barge_in_scenario_structure():
    """Test metric detects barge-in turns correctly."""
    from production.capture.conversation_manager import ConversationManager
    from production.utils.time_utils import Clock

    # Create a scenario with barge-in
    scenario = Scenario(
        id="test_with_barge_in",
        description="Test scenario with barge-in",
        participants={
            "patient": Participant(
                name="patient",
                source_language="es",
                target_language="en"
            )
        },
        turns=[
            ScenarioTurn(
                id="turn1",
                type="play_audio",
                participant="patient",
                barge_in=False,
                start_at_ms=0
            ),
            ScenarioTurn(
                id="turn2",
                type="play_audio",
                participant="patient",
                barge_in=True,  # This is a barge-in!
                start_at_ms=5000
            )
        ]
    )

    clock = Clock(acceleration=1.0)
    conv_manager = ConversationManager(clock=clock, scenario_started_at_ms=0)

    # Create metric
    metric = BargeInMetric(scenario, conv_manager)

    # Test finding barge-in turns
    barge_in_pairs = metric._find_barge_in_turns()
    assert len(barge_in_pairs) == 1
    assert barge_in_pairs[0][0].id == "turn1"  # Previous turn
    assert barge_in_pairs[0][1].id == "turn2"  # Barge-in turn

    print("✅ BargeInMetric correctly identifies barge-in turn pairs")
    print(f"   Found {len(barge_in_pairs)} barge-in pair(s)")


def test_create_metric_factory():
    """Test that metric can be created via factory."""
    from production.capture.conversation_manager import ConversationManager
    from production.utils.time_utils import Clock

    scenario = Scenario(
        id="test",
        description="Test",
        participants={},
        turns=[]
    )

    clock = Clock(acceleration=1.0)
    conv_manager = ConversationManager(clock=clock, scenario_started_at_ms=0)

    # Create via factory
    metric = create_metric("barge_in", scenario, conv_manager)
    assert isinstance(metric, BargeInMetric)
    assert metric.name == "barge_in"

    print("✅ BargeInMetric can be created via factory method")


if __name__ == "__main__":
    print("="*80)
    print("Validating BargeInMetric Implementation")
    print("="*80)
    print()

    try:
        test_metric_registration()
        test_metric_attributes()
        test_metric_methods()
        test_no_barge_in_scenario()
        test_barge_in_scenario_structure()
        test_create_metric_factory()

        print()
        print("="*80)
        print("✅ All validation tests passed!")
        print("="*80)
        print()
        print("Next step: Run the full barge-in test scenario:")
        print("  poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml")

    except Exception as e:
        print()
        print("="*80)
        print(f"❌ Validation failed: {e}")
        print("="*80)
        import traceback
        traceback.print_exc()
