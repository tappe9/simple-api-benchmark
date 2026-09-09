"""Diagnostic-only A/B orchestration and descriptive analysis contracts."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import healthcheck_investigation as investigation
from benchmark import report
from benchmark.contract_test import load_cases
from benchmark.definition import PROFILE
from benchmark.healthcheck import CONTAINER_HEALTHCHECK, EXTERNAL_READINESS
from benchmark.registry import active_benchmark, active_members
from benchmark.results import BenchmarkFailure


def measurement(run: int, rps: float, latency: float, memory: int) -> dict:
    elapsed = 30.0
    requests = int(rps * elapsed)
    actual_rps = requests / elapsed
    return {
        "run": run,
        "requests_per_second": actual_rps,
        "mean_response_time_ms": latency,
        "peak_memory_bytes": memory,
        "memory_samples": 4,
        "elapsed_seconds": elapsed,
        "successful_requests": requests,
        "response_bytes": requests * 10,
    }


def observed_run(run: int, rps: float, latency: float, memory: int, *, probe_execs: int) -> dict:
    return {
        **measurement(run, rps, latency, memory),
        "health_probe_events": {
            "total_execs": probe_execs,
            "probe_execs": probe_execs,
            "non_probe_execs": 0,
            "probe_start_timestamps_ns": list(range(1, probe_execs + 1)),
        },
    }


def policy_observation(policy: str, rps_values=(100.0, 110.0, 120.0)) -> dict:
    probe_execs = 2 if policy == CONTAINER_HEALTHCHECK else 0
    runs = [
        investigation.split_observation(
            observed_run(index, rps, 10.0 + index, 1000 + index, probe_execs=probe_execs)
        )
        for index, rps in enumerate(rps_values, start=1)
    ]
    return {
        "policy": policy,
        "readiness": {
            "mechanism": policy,
            "attempts": 2 if policy == CONTAINER_HEALTHCHECK else 1,
            "duration_seconds": 0.5,
        },
        "container": {
            "id": "a" * 64,
            "image_id": "sha256:" + "b" * 64,
            "command": ["server"],
            "postgresql_version": "PostgreSQL 18.6",
        },
        "contract_checks": 2 * len(load_cases()),
        "endpoints": [
            {
                "endpoint": "/json",
                "warmup": {"health_probe_events": runs[0]["health_probe_events"]},
                "runs": runs,
                "selected": runs[1]["measurement"],
            }
        ],
    }


class AnalysisTests(unittest.TestCase):
    def test_split_observation_keeps_strict_measurement_separate_from_probe_evidence(self):
        source = observed_run(1, 100.0, 11.0, 1001, probe_execs=2)
        result = investigation.split_observation(source)
        self.assertEqual(set(result), {"measurement", "health_probe_events"})
        self.assertNotIn("health_probe_events", result["measurement"])
        self.assertEqual(result["health_probe_events"]["probe_execs"], 2)

    def test_analysis_reports_selected_deltas_spreads_and_paired_direction(self):
        baseline = policy_observation(CONTAINER_HEALTHCHECK, (100.0, 110.0, 120.0))
        controlled = policy_observation(EXTERNAL_READINESS, (105.0, 111.0, 119.0))
        result = investigation.analyze_pair(baseline, controlled)
        throughput = result["endpoints"][0]["metrics"]["requests_per_second"]
        self.assertAlmostEqual(throughput["selected_absolute_delta"], 1.0)
        self.assertAlmostEqual(throughput["selected_percent_delta"], 100.0 / 110.0)
        self.assertEqual(throughput["baseline_range"], [100.0, 120.0])
        self.assertEqual(throughput["controlled_range"], [105.0, 119.0])
        self.assertEqual(throughput["paired_direction"], {"higher": 2, "equal": 0, "lower": 1})

    def test_metric_summary_handles_zero_denominator_without_infinite_percentage(self):
        result = investigation.metric_comparison([0.0, 0.0, 0.0], [0.0, 1.0, 2.0], 0.0, 1.0)
        self.assertIsNone(result["selected_percent_delta"])
        self.assertEqual(result["paired_direction"], {"higher": 2, "equal": 1, "lower": 0})

    def test_analysis_rejects_mismatched_policies_endpoints_or_incomplete_runs(self):
        baseline = policy_observation(CONTAINER_HEALTHCHECK)
        controlled = policy_observation(EXTERNAL_READINESS)
        broken_values = []
        wrong_policy = copy.deepcopy(baseline)
        wrong_policy["policy"] = EXTERNAL_READINESS
        broken_values.append((wrong_policy, controlled))
        wrong_endpoint = copy.deepcopy(controlled)
        wrong_endpoint["endpoints"][0]["endpoint"] = "/cpu"
        broken_values.append((baseline, wrong_endpoint))
        incomplete = copy.deepcopy(controlled)
        incomplete["endpoints"][0]["runs"].pop()
        broken_values.append((baseline, incomplete))
        for pair in broken_values:
            with self.subTest(pair=pair), self.assertRaises(BenchmarkFailure):
                investigation.analyze_pair(*pair)


class FakeEnvironment:
    def __init__(self, implementation_id: str, policy: str, calls: list[tuple[str, str]]):
        self.implementation_id = implementation_id
        self.health_policy = policy
        self.calls = calls
        self.readiness = {
            "attempts": 2 if policy == CONTAINER_HEALTHCHECK else 1,
            "duration_seconds": 0.25,
        }
        self.cleaned = False

    def build(self, implementation_id: str):
        self.calls.append((implementation_id, self.health_policy))

    def start(self, implementation_id: str):
        return {
            "id": "a" * 64,
            "image_id": "sha256:" + "b" * 64,
            "command": [implementation_id],
            "postgresql_version": "PostgreSQL 18.6",
        }

    def check(self):
        return None

    def measure(self, endpoint: str, duration: int, index: int):
        probe_execs = 2 if self.health_policy == CONTAINER_HEALTHCHECK else 0
        if index == 0:
            run = 1
        else:
            run = index
        policy_bonus = 1.0 if self.health_policy == EXTERNAL_READINESS else 0.0
        endpoint_bonus = {"/json": 0.0, "/db/42": 10.0, "/cpu": 20.0}[endpoint]
        return observed_run(
            run,
            100.0 + endpoint_bonus + run + policy_bonus,
            10.0 + run,
            1000 + run,
            probe_execs=probe_execs,
        )

    def cleanup(self):
        self.cleaned = True


class OrchestrationTests(unittest.TestCase):
    def _collect(self, *, failing=False):
        calls = []
        environments = []

        def factory(implementation_id: str, policy: str):
            if failing and len(environments) == 2:
                raise BenchmarkFailure("synthetic factory failure")
            value = FakeEnvironment(implementation_id, policy, calls)
            environments.append(value)
            return value

        metadata = {"source_commit": "c" * 40, "source_tree": "d" * 40}
        result = investigation.collect_investigation(
            config=copy.deepcopy(PROFILE),
            metadata=metadata,
            environment_factory=factory,
            contract=lambda _url, *, implementation: 2 * len(load_cases()),
            now=iter(
                [
                    "2026-09-09T02:00:00+00:00",
                    "2026-09-09T03:00:00+00:00",
                ]
            ).__next__,
        )
        return result, calls, environments

    def test_collection_alternates_policy_order_uses_full_profile_and_cleans_each_environment(self):
        result, calls, environments = self._collect()
        expected_calls = []
        for index, implementation_id in enumerate(active_members()):
            order = (
                (CONTAINER_HEALTHCHECK, EXTERNAL_READINESS)
                if index % 2 == 0
                else (EXTERNAL_READINESS, CONTAINER_HEALTHCHECK)
            )
            expected_calls.extend((implementation_id, policy) for policy in order)
        self.assertEqual(calls, expected_calls)
        self.assertTrue(all(value.cleaned for value in environments))
        self.assertEqual(result["conditions"], PROFILE)
        self.assertEqual(result["benchmark"], active_benchmark())
        self.assertEqual(result["official"], False)
        self.assertEqual(result["publishable"], False)
        self.assertEqual(result["mode"], "healthcheck-investigation")
        self.assertEqual([row["implementation"] for row in result["implementations"]], active_members())
        for implementation in result["implementations"]:
            self.assertEqual(len(implementation["policy_order"]), 2)
            self.assertEqual(len(implementation["policies"]), 2)
            for policy in implementation["policies"]:
                self.assertEqual([item["endpoint"] for item in policy["endpoints"]], PROFILE["endpoints"])
                self.assertEqual(len(policy["endpoints"][0]["runs"]), 3)

    def test_factory_failure_does_not_produce_a_partial_diagnostic(self):
        with self.assertRaises(BenchmarkFailure):
            self._collect(failing=True)

    def test_diagnostic_is_rejected_by_official_report_validation(self):
        diagnostic, _, _ = self._collect()
        with self.assertRaises(BenchmarkFailure):
            report.validate_report(diagnostic)


class OutputSafetyTests(unittest.TestCase):
    def test_output_must_stay_below_dedicated_cache_root_and_reject_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "healthcheck-investigation"
            root.mkdir()
            self.assertEqual(
                investigation.validate_output_path(root / "result.json", cache_root=root),
                root / "result.json",
            )
            with self.assertRaises(BenchmarkFailure):
                investigation.validate_output_path(root.parent / "outside.json", cache_root=root)
            outside = Path(directory) / "outside"
            outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(BenchmarkFailure):
                investigation.validate_output_path(root / "link" / "result.json", cache_root=root)


if __name__ == "__main__":
    unittest.main()
