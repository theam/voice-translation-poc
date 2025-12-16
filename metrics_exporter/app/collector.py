from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable

from prometheus_client.core import GaugeMetricFamily

from .config import ExporterConfig
from .mongo_access import MongoAccessor

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Prometheus collector that surfaces evaluation and test metrics from MongoDB."""

    def __init__(self, accessor: MongoAccessor, config: ExporterConfig):
        self._accessor = accessor
        self._config = config

    def _metric_families(self) -> Dict[str, GaugeMetricFamily]:
        """Create metric families keyed by metric name."""

        families = {
            "evaluation_score": GaugeMetricFamily(
                "evaluation_score",
                "Overall evaluation score (0-100) for each environment/target pair.",
                labels=["environment", "target_system"],
            ),
            "evaluation_metric_value": GaugeMetricFamily(
                "evaluation_metric_value",
                "Aggregated evaluation-level metrics.",
                labels=["environment", "target_system", "metric_name"],
            ),
            "evaluation_tests_total": GaugeMetricFamily(
                "evaluation_tests_total",
                "Total number of tests executed in the evaluation.",
                labels=["environment", "target_system"],
            ),
            "evaluation_tests_passed": GaugeMetricFamily(
                "evaluation_tests_passed",
                "Number of tests that passed in the evaluation.",
                labels=["environment", "target_system"],
            ),
            "evaluation_tests_failed": GaugeMetricFamily(
                "evaluation_tests_failed",
                "Number of tests that failed in the evaluation.",
                labels=["environment", "target_system"],
            ),
            "evaluation_passed": GaugeMetricFamily(
                "evaluation_passed",
                "Whether the evaluation run passed (status=completed and no failed tests).",
                labels=["environment", "target_system"],
            ),
            "evaluation_running": GaugeMetricFamily(
                "evaluation_running",
                "Whether the evaluation run is currently running.",
                labels=["environment", "target_system"],
            ),
            "test_run_score": GaugeMetricFamily(
                "test_run_score",
                "Overall score (0-100) for a specific test run.",
                labels=["environment", "target_system", "test_id"],
            ),
            "test_run_metric_value": GaugeMetricFamily(
                "test_run_metric_value",
                "Value of a specific metric for a given test run.",
                labels=["environment", "target_system", "test_id", "metric_name"],
            ),
            "test_run_metric_passed": GaugeMetricFamily(
                "test_run_metric_passed",
                "Whether a given metric for a test run passed its threshold.",
                labels=["environment", "target_system", "test_id", "metric_name"],
            ),
            "evaluation_run_count": GaugeMetricFamily(
                "evaluation_run_count",
                "Total number of evaluation runs with scores for each environment/target pair.",
                labels=["environment", "target_system"],
            ),
            "test_run_count": GaugeMetricFamily(
                "test_run_count",
                "Total number of test runs with scores for each test_id.",
                labels=["environment", "target_system", "test_id"],
            ),
            "evaluation_run_discrete_score": GaugeMetricFamily(
                "evaluation_run_discrete_score",
                "Discrete evaluation run score (0-100) for each individual evaluation execution.",
                labels=["environment", "target_system", "evaluation_run_id"],
            ),
            "test_run_discrete_score": GaugeMetricFamily(
                "test_run_discrete_score",
                "Discrete test run score (0-100) for each individual test execution.",
                labels=["environment", "target_system", "test_id", "evaluation_run_id", "test_run_id"],
            ),
            "evaluation_run_sequence_score": GaugeMetricFamily(
                "evaluation_run_sequence_score",
                "Evaluation run scores with sequence numbers (1=oldest, max=newest).",
                labels=["series", "environment", "target_system", "run_seq"],
            ),
            "test_run_sequence_score": GaugeMetricFamily(
                "test_run_sequence_score",
                "Test run scores with sequence numbers (1=oldest, max=newest).",
                labels=["series", "environment", "target_system", "test_id", "run_seq"],
            ),
            "calibration_run_sequence_status": GaugeMetricFamily(
                "calibration_run_sequence_status",
                "Calibration run pass/fail status with sequence numbers (100=passed, 50=failed).",
                labels=["series", "environment", "run_seq"],
            ),
            "calibration_run_count": GaugeMetricFamily(
                "calibration_run_count",
                "Total number of calibration runs per environment.",
                labels=["environment"],
            ),
        }
        return families

    def _compute_cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self._config.lookback_days)

    def collect(self) -> Iterable[GaugeMetricFamily]:
        cutoff = self._compute_cutoff()

        evaluation_runs = self._accessor.fetch_evaluation_runs(cutoff)
        latest_runs = self._latest_runs_by_environment_and_target(evaluation_runs)
        evaluation_by_id: Dict = {doc.get("_id"): doc for doc in latest_runs if doc.get("_id") is not None}

        # Build mappings from ALL evaluation runs for counting purposes
        all_env_by_eval_id: Dict = {doc.get("_id"): doc.get("environment") for doc in evaluation_runs if doc.get("_id") is not None}
        all_target_system_by_eval_id: Dict = {
            doc.get("_id"): doc.get("target_system") for doc in evaluation_runs if doc.get("_id") is not None
        }
        # Build mapping from evaluation_run_id to MongoDB _id for lookups
        eval_run_id_to_mongo_id: Dict = {
            doc.get("evaluation_run_id"): doc.get("_id") for doc in evaluation_runs
            if doc.get("evaluation_run_id") is not None and doc.get("_id") is not None
        }

        # Fetch test runs from ALL evaluation runs within lookback period
        all_eval_ids = list(all_env_by_eval_id.keys())
        test_runs = self._accessor.fetch_test_runs(all_eval_ids)

        # Keep original mappings for latest runs (used for scores)
        env_by_eval_id: Dict = {doc.get("_id"): doc.get("environment") for doc in latest_runs if doc.get("_id") is not None}
        target_system_by_eval_id: Dict = {
            doc.get("_id"): doc.get("target_system") for doc in latest_runs if doc.get("_id") is not None
        }

        families = self._metric_families()

        # Count evaluation runs by environment/target (only those with scores, exclude calibrations)
        eval_run_counts: Dict = {}
        for run in evaluation_runs:
            if run.get("score") is None:
                continue
            if run.get("target_system") == "calibration":
                continue
            env = run.get("environment", "unknown")
            target = run.get("target_system", "unknown")
            key = (env, target)
            eval_run_counts[key] = eval_run_counts.get(key, 0) + 1

        for (env, target), count in eval_run_counts.items():
            families["evaluation_run_count"].add_metric([env, target], float(count))

        # Count test runs by environment/target/test_id (only those with scores, exclude calibrations)
        test_run_counts: Dict = {}
        for test_doc in test_runs:
            eval_id = test_doc.get("evaluation_run_id")
            environment = all_env_by_eval_id.get(eval_id)
            target_system = all_target_system_by_eval_id.get(eval_id)
            if environment is None or target_system is None:
                continue
            if target_system == "calibration":
                continue
            if test_doc.get("score") is None:
                continue
            test_id = str(test_doc.get("test_id"))
            key = (environment, target_system, test_id)
            test_run_counts[key] = test_run_counts.get(key, 0) + 1

        for (env, target, test_id), count in test_run_counts.items():
            families["test_run_count"].add_metric([env, target, test_id], float(count))

        # Add discrete scores for ALL evaluation runs (not just latest, exclude calibrations)
        for eval_doc in evaluation_runs:
            environment = eval_doc.get("environment", "unknown")
            target_system = eval_doc.get("target_system", "unknown")
            if target_system == "calibration":
                continue
            # Use MongoDB _id as the unique identifier
            evaluation_run_id = str(eval_doc.get("_id", "unknown"))
            score = eval_doc.get("score")
            if score is not None:
                families["evaluation_run_discrete_score"].add_metric(
                    [environment, target_system, evaluation_run_id], float(score)
                )

        # Add discrete scores for ALL test runs (exclude calibrations)
        for test_doc in test_runs:
            eval_id = test_doc.get("evaluation_run_id")
            environment = all_env_by_eval_id.get(eval_id)
            target_system = all_target_system_by_eval_id.get(eval_id)
            if environment is None or target_system is None:
                continue
            if target_system == "calibration":
                continue

            test_id = str(test_doc.get("test_id"))
            # Use MongoDB _id for test_run_id
            test_run_id = str(test_doc.get("_id", "unknown"))
            # Convert evaluation_run_id string to MongoDB _id
            evaluation_run_id = str(eval_run_id_to_mongo_id.get(eval_id, eval_id))
            score = test_doc.get("score")

            if score is not None:
                families["test_run_discrete_score"].add_metric(
                    [environment, target_system, test_id, evaluation_run_id, test_run_id],
                    float(score)
                )

        # Get finished_at from evaluation runs for test run sequencing
        eval_finished_at = {}
        for eval_doc in evaluation_runs:
            eval_id = eval_doc.get("_id")
            if eval_id:
                eval_finished_at[eval_id] = eval_doc.get("finished_at") or eval_doc.get("started_at")

        # Add sequence-based scores for ALL evaluation runs (exclude calibrations)
        runs_by_env_target_seq = {}
        for eval_doc in evaluation_runs:
            if eval_doc.get("target_system") == "calibration":
                continue
            environment = eval_doc.get("environment", "unknown")
            target_system = eval_doc.get("target_system", "unknown")
            key = (environment, target_system)
            if key not in runs_by_env_target_seq:
                runs_by_env_target_seq[key] = []
            runs_by_env_target_seq[key].append(eval_doc)

        # First pass: calculate the maximum sequence length across all series
        max_seq = 0
        series_runs = {}
        for (environment, target_system), runs in runs_by_env_target_seq.items():
            # Sort by finished_at (oldest first)
            sorted_runs = sorted(
                runs,
                key=lambda x: x.get("finished_at") or x.get("started_at") or datetime.min,
                reverse=False  # oldest first
            )
            # Filter runs with scores
            runs_with_scores = [run for run in sorted_runs if run.get("score") is not None]
            series_runs[(environment, target_system)] = runs_with_scores
            max_seq = max(max_seq, len(runs_with_scores))

        # Second pass: emit metrics with re-sequenced positions (right-aligned)
        for (environment, target_system), runs_with_scores in series_runs.items():
            n = len(runs_with_scores)
            series_label = f"{environment}/{target_system}"
            # Calculate the starting sequence number to right-align with max_seq
            start_seq = max_seq - n + 1
            for i, run in enumerate(runs_with_scores):
                run_seq = start_seq + i
                families["evaluation_run_sequence_score"].add_metric(
                    [series_label, environment, target_system, str(run_seq)], float(run.get("score"))
                )

        # Add sequence-based status for calibration runs
        calibration_runs = [
            run for run in evaluation_runs
            if run.get("target_system") == "calibration"
        ]

        # Group calibration runs by environment
        calibration_by_env = {}
        for run in calibration_runs:
            environment = run.get("environment", "unknown")
            if environment not in calibration_by_env:
                calibration_by_env[environment] = []
            calibration_by_env[environment].append(run)

        # Calculate max sequence for calibrations
        max_cal_seq = 0
        calibration_series_runs = {}
        for environment, runs in calibration_by_env.items():
            # Sort by finished_at (oldest first)
            sorted_runs = sorted(
                runs,
                key=lambda x: x.get("finished_at") or x.get("started_at") or datetime.min,
                reverse=False
            )
            # Filter runs with calibration_status
            runs_with_status = [run for run in sorted_runs if run.get("calibration_status") is not None]
            calibration_series_runs[environment] = runs_with_status
            max_cal_seq = max(max_cal_seq, len(runs_with_status))

        # Emit calibration sequence metrics (right-aligned)
        for environment, runs_with_status in calibration_series_runs.items():
            n = len(runs_with_status)
            series_label = environment
            start_seq = max_cal_seq - n + 1
            for i, run in enumerate(runs_with_status):
                run_seq = start_seq + i
                # Map status to value: 100 for passed, 50 for failed
                status = run.get("calibration_status", "failed")
                status_value = 100.0 if status == "passed" else 50.0
                families["calibration_run_sequence_status"].add_metric(
                    [series_label, environment, str(run_seq)], status_value
                )

        # Emit calibration run counts per environment
        for environment, runs in calibration_by_env.items():
            count = len(runs)
            families["calibration_run_count"].add_metric([environment], float(count))

        # Add sequence-based scores for ALL test runs (exclude calibrations)
        test_runs_by_key_seq = {}
        for test_doc in test_runs:
            eval_id = test_doc.get("evaluation_run_id")
            environment = all_env_by_eval_id.get(eval_id)
            target_system = all_target_system_by_eval_id.get(eval_id)
            if environment is None or target_system is None:
                continue
            if target_system == "calibration":
                continue

            test_id = str(test_doc.get("test_id"))
            key = (environment, target_system, test_id)
            if key not in test_runs_by_key_seq:
                test_runs_by_key_seq[key] = []

            # Add finished_at from evaluation run to test doc for sorting
            test_doc_with_time = dict(test_doc)
            test_doc_with_time["finished_at"] = eval_finished_at.get(eval_id)
            test_runs_by_key_seq[key].append(test_doc_with_time)

        # First pass: calculate the maximum sequence length across all test series
        max_test_seq = 0
        test_series_runs = {}
        for (environment, target_system, test_id), runs in test_runs_by_key_seq.items():
            # Sort by finished_at (oldest first)
            sorted_runs = sorted(
                runs,
                key=lambda x: x.get("finished_at") or datetime.min,
                reverse=False  # oldest first
            )
            # Filter runs with scores
            runs_with_scores = [run for run in sorted_runs if run.get("score") is not None]
            test_series_runs[(environment, target_system, test_id)] = runs_with_scores
            max_test_seq = max(max_test_seq, len(runs_with_scores))

        # Second pass: emit metrics with re-sequenced positions (right-aligned)
        for (environment, target_system, test_id), runs_with_scores in test_series_runs.items():
            n = len(runs_with_scores)
            series_label = f"{environment}/{target_system}/{test_id}"
            # Calculate the starting sequence number to right-align with max_test_seq
            start_seq = max_test_seq - n + 1
            for i, run in enumerate(runs_with_scores):
                run_seq = start_seq + i
                families["test_run_sequence_score"].add_metric(
                    [series_label, environment, target_system, test_id, str(run_seq)], float(run.get("score"))
                )

        for eval_doc in latest_runs:
            environment = eval_doc.get("environment", "unknown")
            target_system = eval_doc.get("target_system", "unknown")

            # Skip calibration runs
            if target_system == "calibration":
                continue

            score = eval_doc.get("score")
            if score is not None:
                families["evaluation_score"].add_metric([environment, target_system], score)

            for metric_name, value in (eval_doc.get("metrics") or {}).items():
                if value is not None:
                    families["evaluation_metric_value"].add_metric([environment, target_system, metric_name], float(value))

            num_tests = eval_doc.get("num_tests")
            if num_tests is not None:
                families["evaluation_tests_total"].add_metric([environment, target_system], float(num_tests))

            num_passed = eval_doc.get("num_passed")
            if num_passed is not None:
                families["evaluation_tests_passed"].add_metric([environment, target_system], float(num_passed))

            num_failed = eval_doc.get("num_failed")
            if num_failed is not None:
                families["evaluation_tests_failed"].add_metric([environment, target_system], float(num_failed))

            status = eval_doc.get("status", "unknown")
            passed_value = 1.0 if status == "completed" and num_failed == 0 else 0.0
            running_value = 1.0 if status == "running" else 0.0
            families["evaluation_passed"].add_metric([environment, target_system], passed_value)
            families["evaluation_running"].add_metric([environment, target_system], running_value)

        for test_doc in test_runs:
            eval_id = test_doc.get("evaluation_run_id")
            environment = env_by_eval_id.get(eval_id)
            target_system = target_system_by_eval_id.get(eval_id)
            eval_doc = evaluation_by_id.get(eval_id)
            if environment is None or target_system is None or eval_doc is None:
                logger.debug("Skipping test run with unknown evaluation id: %s", eval_id)
                continue
            if target_system == "calibration":
                continue

            test_id = str(test_doc.get("test_id"))

            score = test_doc.get("score")
            if score is not None:
                families["test_run_score"].add_metric([environment, target_system, test_id], float(score))

            for metric_name, metric_data in (test_doc.get("metrics") or {}).items():
                if not isinstance(metric_data, dict):
                    continue
                name = metric_data.get("metric_name") or metric_name
                value = metric_data.get("value")
                if value is not None:
                    families["test_run_metric_value"].add_metric(
                        [environment, target_system, test_id, name], float(value)
                    )

                passed = metric_data.get("passed")
                passed_value = 1.0 if passed else 0.0
                families["test_run_metric_passed"].add_metric(
                    [environment, target_system, test_id, name], passed_value
                )

        return families.values()

    @staticmethod
    def _latest_runs_by_environment_and_target(evaluation_runs):
        latest_by_env_target: Dict = {}

        for run in evaluation_runs:
            environment = run.get("environment", "unknown")
            target_system = run.get("target_system", "unknown")
            key = (environment, target_system)

            finished = run.get("finished_at") or run.get("started_at")

            if key not in latest_by_env_target:
                latest_by_env_target[key] = run
                continue

            prev = latest_by_env_target[key]
            prev_finished = prev.get("finished_at") or prev.get("started_at")

            if finished and (prev_finished is None or finished > prev_finished):
                latest_by_env_target[key] = run

        return list(latest_by_env_target.values())
