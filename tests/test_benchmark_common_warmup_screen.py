"""Synthetic tests for the separately versioned, endpoint-isolated screen."""

import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.contract_test import load_cases
from benchmark.healthcheck import EXTERNAL_READINESS
from benchmark.results import BenchmarkFailure


class Environment:
    health_policy = EXTERNAL_READINESS
    connections = 50
    request_timeout = 15

    def __init__(self, root, index, fail=None):
        self.artifacts = root / "raw"
        self.artifacts.mkdir(parents=True)
        self.index = index
        self.fail = fail
        self.events = []
        self.readiness = {"path": "/health", "attempts": 1}

    def build(self, identifier):
        self.events.append(("build", identifier))
        if self.fail == "build":
            raise BenchmarkFailure("build failed")

    def start(self, identifier):
        self.events.append(("start", identifier))
        return {
            "id": f"{self.index:064x}",
            "image_id": "sha256:" + identifier,
            "postgres": {"id": f"{100 + self.index:064x}"},
        }

    def check(self):
        self.events.append("check")

    def measure(self, endpoint, duration, index):
        self.events.append((endpoint, duration, index))
        if self.fail == "measure":
            raise BenchmarkFailure("measure failed")
        if self.fail == "interrupt":
            raise KeyboardInterrupt()
        return {
            "requests_per_second": 100,
            "p95_response_time_ms": 2,
            "successful_requests": 100,
            "elapsed_seconds": duration,
        }

    def cleanup(self):
        self.events.append("cleanup")
        if self.fail == "cleanup":
            raise BenchmarkFailure("cleanup failed")


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("benchmark.common_warmup_screen"))
        self.module = importlib.import_module("benchmark.common_warmup_screen")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        p = patch.object(self.module, "CACHE_ROOT", self.cache)
        p.start()
        self.addCleanup(p.stop)
        self.output = self.cache / "run"
        self.envs = []
        self.contract_envs = []
        self.metadata = {"source_commit": "a" * 40, "source_tree": "b" * 40}

    def run_study(self, fail=None, count=None):
        def factory(root):
            env = Environment(root, len(self.envs) + 1, fail)
            self.envs.append(env)
            return env

        def contract(*args, **kwargs):
            self.contract_envs.append(self.envs[-1])
            return 2 * len(load_cases()) if count is None else count

        return self.module.run_study(
            self.output, factory, metadata=self.metadata, contract=contract
        )

    def test_fixed_schedule_sacrificial_contracts_isolated_endpoints_and_no_publication(self):
        result = self.run_study()
        self.assertEqual(len(self.envs), 21)
        self.assertEqual(self.contract_envs, self.envs[:3])
        self.assertEqual(len(result["validations"]), 3)
        self.assertEqual(len(result["attempts"]), 18)
        first = [(a["implementation"], a["endpoint"]) for a in result["attempts"][:9]]
        second = [(a["implementation"], a["endpoint"]) for a in result["attempts"][9:]]
        self.assertEqual(first[::-1], second)
        self.assertEqual(len(set(first)), 9)
        for env in self.envs:
            self.assertEqual(env.events[-1], "cleanup")
        for env in self.envs[:3]:
            self.assertFalse(any(isinstance(e, tuple) and e[0].startswith("/") for e in env.events))
        for env, attempt in zip(self.envs[3:], result["attempts"]):
            loads = [e for e in env.events if isinstance(e, tuple) and e[0].startswith("/")]
            self.assertEqual(
                loads, [(attempt["endpoint"], 5 if i == 0 else 30, i) for i in range(9)]
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["protocol_id"], "common-warmup-screen-v1")
        self.assertEqual(result["assessment"]["screened_candidate_seconds"], [5, 35, 65])
        self.assertFalse(result["official"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result, json.loads((self.output / "screen.json").read_text()))
        self.assertTrue((self.output / "checksums.json").exists())
        from benchmark.report import validate_report

        with self.assertRaises(BenchmarkFailure):
            validate_report(result)

    def test_one_second_round_failure_prevents_common_candidate(self):
        envs = []

        def factory(root):
            env = Environment(root, len(envs) + 1)
            original = env.measure

            def measure(endpoint, duration, index):
                result = original(endpoint, duration, index)
                if env.index == 21 and index == 5:
                    result["requests_per_second"] = 200
                return result

            env.measure = measure
            envs.append(env)
            return env

        result = self.module.run_study(
            self.output,
            factory,
            metadata=self.metadata,
            contract=lambda *a, **k: 2 * len(load_cases()),
        )
        self.assertEqual(result["assessment"]["outcome"], "inconclusive")
        self.assertEqual(result["assessment"]["screened_candidate_seconds"], [])
        self.assertTrue(result["attempts"][0]["analysis"]["screened_candidate_seconds"])
        self.assertFalse(result["attempts"][-1]["analysis"]["screened_candidate_seconds"])

    def test_failure_stops_and_retains_unstarted_work_without_retry(self):
        for fail in ("build", "measure", "cleanup", "interrupt"):
            with self.subTest(fail=fail):
                self.output = self.cache / fail
                self.envs = []
                with self.assertRaises((BenchmarkFailure, KeyboardInterrupt)):
                    self.run_study(fail=fail)
                result = json.loads((self.output / "screen.json").read_text())
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("assessment", result)
                self.assertLessEqual(len(self.envs), 4)
                self.assertEqual(self.envs[-1].events[-1], "cleanup")
                self.assertTrue((self.output / "checksums.json").exists())
                self.assertTrue(all(a["status"] == "not-started" for a in result["attempts"][1:]))

    def test_contract_count_fails_before_any_measured_trace(self):
        with self.assertRaises(BenchmarkFailure):
            self.run_study(count=True)
        self.assertEqual(len(self.envs), 1)
        self.assertEqual(self.envs[0].events[-1], "cleanup")

    def test_no_overwrite_escape_symlink_or_missing_provenance(self):
        self.run_study()
        before = (self.output / "screen.json").read_bytes()
        with self.assertRaises(BenchmarkFailure):
            self.run_study()
        self.assertEqual(before, (self.output / "screen.json").read_bytes())
        (self.cache / "link").symlink_to(self.cache, target_is_directory=True)
        for path in (self.cache, self.cache / ".." / "outside", self.cache / "link" / "new"):
            with self.assertRaises(BenchmarkFailure):
                self.module.validate_directory(path)
        self.output = self.cache / "missing-source"
        self.metadata = {}
        with self.assertRaises(BenchmarkFailure):
            self.run_study()

    def test_trace_rejects_reused_identity_or_different_validated_image(self):
        for kind in ("api", "database", "image"):
            with self.subTest(kind=kind):
                self.output = self.cache / kind
                envs = []

                def factory(root):
                    env = Environment(root, len(envs) + 1)
                    original = env.start

                    def start(identifier):
                        result = original(identifier)
                        if len(envs) > 3:
                            if kind == "api":
                                result["id"] = f"{1:064x}"
                            elif kind == "database":
                                result["postgres"]["id"] = f"{101:064x}"
                            else:
                                result["image_id"] = "changed"
                        return result

                    env.start = start
                    envs.append(env)
                    return env

                with self.assertRaises(BenchmarkFailure):
                    self.module.run_study(
                        self.output,
                        factory,
                        metadata=self.metadata,
                        contract=lambda *a, **k: 2 * len(load_cases()),
                    )
                self.assertEqual(len(envs), 4)
                self.assertFalse(
                    any(isinstance(e, tuple) and e[0].startswith("/") for e in envs[-1].events)
                )

    def test_analysis_exact_candidates_reference_and_all_later_windows(self):
        def windows(rps, p95=None):
            return [
                {"requests_per_second": r, "p95_response_time_ms": p}
                for r, p in zip(rps, p95 or [2] * 8)
            ]

        analyze = self.module.analyze_windows
        result = analyze(windows([50, 80, 100, 100, 100, 100, 100, 100]))
        self.assertEqual(result["screened_candidate_seconds"], [65])
        self.assertEqual(result["reference_window_indices"], [6, 7, 8])
        self.assertFalse(
            analyze(windows([100, 100, 100, 100, 120, 100, 100, 100]))["screened_candidate_seconds"]
        )
        # Tiny strict monotonic noise is reported, not automatically disqualifying.
        self.assertEqual(
            analyze(windows([100] * 5 + [99, 100, 101]))["screened_candidate_seconds"], [5, 35, 65]
        )
        self.assertTrue(
            analyze(windows([100] * 5 + [99, 100, 101]))["strict_monotonic_reference_trend"]
        )
        self.assertFalse(
            analyze(windows([100] * 8, [2, 2, 2, 2, 3, 2, 2, 2]))["screened_candidate_seconds"]
        )
        # Both bands and within-candidate range matter: +/-4% fits bands but range8% fails.
        self.assertFalse(
            analyze(windows([96, 104, 96, 104, 96, 100, 100, 100]))["screened_candidate_seconds"]
        )
        for invalid in ([100] * 7, [100] * 7 + [float("nan")], [100] * 7 + [True]):
            with self.assertRaises(BenchmarkFailure):
                analyze(windows(invalid))

    def test_decimal_threshold_roundoff_passes_but_material_excess_fails(self):
        def windows(rps, p95):
            return [{"requests_per_second": r, "p95_response_time_ms": p} for r, p in zip(rps, p95)]

        analyze = self.module.analyze_windows
        for rps, p95 in (
            ([100] * 8, [2.2] * 5 + [2] * 3),
            ([1.05] * 5 + [1] * 3, [2] * 8),
            ([1] * 5 + [0.975, 1, 1.025], [2] * 5 + [1.9, 2, 2.1]),
        ):
            self.assertEqual(analyze(windows(rps, p95))["screened_candidate_seconds"], [5, 35, 65])
        self.assertFalse(
            analyze(windows([1.05000001] * 5 + [1] * 3, [2] * 8))["screened_candidate_seconds"]
        )
        self.assertFalse(
            analyze(windows([100] * 8, [2.20000001] * 5 + [2] * 3))["screened_candidate_seconds"]
        )

    def test_analysis_inclusive_thresholds_and_unstable_reference(self):
        def windows(values):
            return [{"requests_per_second": r, "p95_response_time_ms": 2} for r in values]

        self.assertEqual(
            self.module.analyze_windows(windows([95] * 5 + [100] * 3))[
                "screened_candidate_seconds"
            ],
            [5, 35, 65],
        )
        self.assertFalse(
            self.module.analyze_windows(windows([94.99] * 5 + [100] * 3))[
                "screened_candidate_seconds"
            ]
        )
        self.assertFalse(
            self.module.analyze_windows(windows([100] * 5 + [90, 100, 110]))[
                "screened_candidate_seconds"
            ]
        )


if __name__ == "__main__":
    unittest.main()
