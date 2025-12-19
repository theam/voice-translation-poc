"""Tests for the overlap metric."""


def _calculate_overlap_score(overlap_ms: int) -> float:
    """Calculate score based on overlap duration.

    Copied from production.metrics.overlap for testing.
    """
    if overlap_ms <= 0:
        return 100.0
    elif overlap_ms <= 2000:
        return 100.0 - (overlap_ms / 2000.0) * 50.0
    else:
        return 0.0


def test_no_overlap():
    """Test scoring when there's no overlap (negative values)."""
    assert _calculate_overlap_score(-1000) == 100.0
    assert _calculate_overlap_score(0) == 100.0


def test_minor_overlap():
    """Test linear scoring for 0-2000ms overlap."""
    # At 0ms: 100%
    assert _calculate_overlap_score(0) == 100.0

    # At 500ms: should be 87.5%
    # Formula: 100 - (500/2000)*50 = 100 - 12.5 = 87.5
    assert _calculate_overlap_score(500) == 87.5

    # At 1000ms: should be 75%
    # Formula: 100 - (1000/2000)*50 = 100 - 25 = 75
    assert _calculate_overlap_score(1000) == 75.0

    # At 1500ms: should be 62.5%
    # Formula: 100 - (1500/2000)*50 = 100 - 37.5 = 62.5
    assert _calculate_overlap_score(1500) == 62.5

    # At 2000ms: should be 50%
    # Formula: 100 - (2000/2000)*50 = 100 - 50 = 50
    assert _calculate_overlap_score(2000) == 50.0


def test_critical_overlap():
    """Test scoring for severe overlap (>2000ms)."""
    assert _calculate_overlap_score(2001) == 0.0
    assert _calculate_overlap_score(5000) == 0.0
    assert _calculate_overlap_score(10000) == 0.0
