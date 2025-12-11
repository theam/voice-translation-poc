from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from ..collector import MetricsCollector
from ..config import ExporterConfig


class FakeAccessor:
    def __init__(self, evaluations, tests):
        self._evaluations = evaluations
        self._tests = tests

    def fetch_evaluation_runs(self, cutoff):
        return self._evaluations

    def fetch_test_runs(self, evaluation_ids):
        evaluation_ids = set(evaluation_ids)
        return [test for test in self._tests if test.get("evaluation_run_id") in evaluation_ids]


def _build_collector(evaluations, tests):
    config = ExporterConfig(
        mongo_uri="mongodb://example.com:27017", mongo_db_name="db", lookback_days=7, port=9100
    )
    accessor = FakeAccessor(evaluations, tests)
    return MetricsCollector(accessor, config)


def _to_map(families):
    return {family.name: family for family in families}


def test_collect_emits_evaluation_and_test_metrics():
    eval_id = ObjectId()
    evaluations = [
        {
            "_id": eval_id,
            "evaluation_run_id": "eval-1",
            "environment": "ci",
            "target_system": "voice_live",
            "git_branch": "main",
            "started_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "metrics": {"average_wer": 0.12, "average_semantic_score": 0.9},
            "num_tests": 3,
            "num_passed": 3,
            "num_failed": 0,
            "status": "completed",
            "score": 95.0,
        }
    ]
    tests = [
        {
            "evaluation_run_id": eval_id,
            "test_id": "scenario-a",
            "metrics": {
                "wer": {"metric_name": "wer", "value": 0.1, "passed": True},
                "semantic_score": {"metric_name": "semantic_score", "value": 0.92, "passed": True},
            },
            "score": 96.0,
        }
    ]

    collector = _build_collector(evaluations, tests)
    families = _to_map(list(collector.collect()))

    evaluation_score_samples = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_score"].samples}
    assert evaluation_score_samples[("environment", "ci"), ("target_system", "voice_live")] == 95.0

    eval_metric_samples = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_metric_value"].samples}
    assert eval_metric_samples[("environment", "ci"), ("target_system", "voice_live"), ("metric_name", "average_wer")] == 0.12
    assert eval_metric_samples[(
        ("environment", "ci"),
        ("target_system", "voice_live"),
        ("metric_name", "average_semantic_score"),
    )] == 0.9

    totals_samples = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_tests_total"].samples}
    assert totals_samples[("environment", "ci"), ("target_system", "voice_live")] == 3.0

    passed_samples = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_passed"].samples}
    assert passed_samples[("environment", "ci"), ("target_system", "voice_live")] == 1.0

    running_samples = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_running"].samples}
    assert running_samples[("environment", "ci"), ("target_system", "voice_live")] == 0.0

    test_score_samples = {tuple(sample.labels.items()): sample.value for sample in families["test_run_score"].samples}
    assert test_score_samples[("environment", "ci"), ("target_system", "voice_live"), ("test_id", "scenario-a")] == 96.0

    test_metric_samples = {tuple(sample.labels.items()): sample.value for sample in families["test_run_metric_value"].samples}
    assert test_metric_samples[("environment", "ci"), ("target_system", "voice_live"), ("test_id", "scenario-a"), ("metric_name", "wer")] == 0.1
    assert test_metric_samples[("environment", "ci"), ("target_system", "voice_live"), ("test_id", "scenario-a"), ("metric_name", "semantic_score")] == 0.92

    test_metric_passed_samples = {
        tuple(sample.labels.items()): sample.value for sample in families["test_run_metric_passed"].samples
    }
    assert test_metric_passed_samples[("environment", "ci"), ("target_system", "voice_live"), ("test_id", "scenario-a"), ("metric_name", "wer")] == 1.0
    assert test_metric_passed_samples[("environment", "ci"), ("target_system", "voice_live"), ("test_id", "scenario-a"), ("metric_name", "semantic_score")] == 1.0


def test_collect_uses_latest_run_per_environment_and_target():
    older_eval_id = ObjectId()
    newer_eval_id = ObjectId()

    evaluations = [
        {
            "_id": older_eval_id,
            "evaluation_run_id": "eval-old",
            "environment": "dev",
            "target_system": "voice_live",
            "started_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "finished_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
            "metrics": {"average_wer": 0.2},
            "num_tests": 2,
            "num_failed": 1,
            "status": "completed",
            "score": 80.0,
        },
        {
            "_id": newer_eval_id,
            "evaluation_run_id": "eval-new",
            "environment": "dev",
            "target_system": "voice_live",
            "started_at": datetime(2024, 1, 3, tzinfo=timezone.utc),
            "finished_at": datetime(2024, 1, 4, tzinfo=timezone.utc),
            "metrics": {"average_wer": 0.1},
            "num_tests": 3,
            "num_failed": 0,
            "status": "completed",
            "score": 90.0,
        },
    ]

    tests = [
        {
            "evaluation_run_id": older_eval_id,
            "test_id": "scenario-old",
            "metrics": {"wer": {"metric_name": "wer", "value": 0.2, "passed": False}},
            "score": 70.0,
        },
        {
            "evaluation_run_id": newer_eval_id,
            "test_id": "scenario-new",
            "metrics": {"wer": {"metric_name": "wer", "value": 0.1, "passed": True}},
            "score": 95.0,
        },
    ]

    collector = _build_collector(evaluations, tests)
    families = _to_map(list(collector.collect()))

    evaluation_scores = {tuple(sample.labels.items()): sample.value for sample in families["evaluation_score"].samples}
    assert evaluation_scores == {(("environment", "dev"), ("target_system", "voice_live")): 90.0}

    test_scores = {tuple(sample.labels.items()): sample.value for sample in families["test_run_score"].samples}
    assert test_scores == {(("environment", "dev"), ("target_system", "voice_live"), ("test_id", "scenario-new")): 95.0}


def test_collect_emits_discrete_scores_for_all_runs():
    eval_id_1 = ObjectId()
    eval_id_2 = ObjectId()
    test_id_1 = ObjectId()
    test_id_2 = ObjectId()

    evaluations = [
        {
            "_id": eval_id_1,
            "evaluation_run_id": "eval-1",
            "environment": "dev",
            "target_system": "voice_live",
            "started_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "finished_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
            "score": 85.0,
            "num_tests": 1,
            "num_failed": 0,
            "status": "completed",
        },
        {
            "_id": eval_id_2,
            "evaluation_run_id": "eval-2",
            "environment": "dev",
            "target_system": "voice_live",
            "started_at": datetime(2024, 1, 3, tzinfo=timezone.utc),
            "finished_at": datetime(2024, 1, 4, tzinfo=timezone.utc),
            "score": 92.0,
            "num_tests": 1,
            "num_failed": 0,
            "status": "completed",
        },
    ]

    tests = [
        {
            "_id": test_id_1,
            "evaluation_run_id": eval_id_1,
            "test_id": "scenario-a",
            "score": 88.0,
            "metrics": {},
        },
        {
            "_id": test_id_2,
            "evaluation_run_id": eval_id_2,
            "test_id": "scenario-a",
            "score": 94.0,
            "metrics": {},
        },
    ]

    collector = _build_collector(evaluations, tests)
    families = _to_map(list(collector.collect()))

    # Check that discrete evaluation scores exist for BOTH runs
    discrete_eval_scores = {
        tuple(sample.labels.items()): sample.value for sample in families["evaluation_run_discrete_score"].samples
    }
    assert len(discrete_eval_scores) == 2
    assert discrete_eval_scores[
        (("environment", "dev"), ("target_system", "voice_live"), ("evaluation_run_id", str(eval_id_1)))
    ] == 85.0
    assert discrete_eval_scores[
        (("environment", "dev"), ("target_system", "voice_live"), ("evaluation_run_id", str(eval_id_2)))
    ] == 92.0

    # Check that discrete test scores exist for BOTH test runs
    discrete_test_scores = {
        tuple(sample.labels.items()): sample.value for sample in families["test_run_discrete_score"].samples
    }
    assert len(discrete_test_scores) == 2
    # Verify both test runs are present
    assert any(sample.value == 88.0 for sample in families["test_run_discrete_score"].samples)
    assert any(sample.value == 94.0 for sample in families["test_run_discrete_score"].samples)
