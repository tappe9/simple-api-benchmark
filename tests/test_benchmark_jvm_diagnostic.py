"""Fixed, non-publishing JVM study: synthetic scheduling and failure evidence."""

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

    def __init__(self, root, fail=None):
        self.artifacts = root / "raw"
        self.artifacts.mkdir(parents=True)
        self.events = []
        self.fail = fail
        self.readiness = {"attempts": 1}

    def build(self, identifier):
        self.events.append(("build", identifier))
        if self.fail == "build":
            raise BenchmarkFailure("build failed")

    def start(self, identifier):
        self.events.append(("start", identifier))
        return {"id": "a" * 64, "image_id": "sha256:" + "b" * 64}

    def check(self):
        pass

    def measure(self, endpoint, duration, index):
        self.events.append((endpoint, duration, index))
        if self.fail == "measure":
            raise BenchmarkFailure("measure failed")
        if self.fail == "interrupt":
            raise KeyboardInterrupt()
        return {
            "requests_per_second": [100, 100, 101, 100, 101][index],
            "p95_response_time_ms": 2,
            "successful_requests": 100,
            "elapsed_seconds": duration,
        }

    def cleanup(self):
        self.events.append("cleanup")
        if self.fail == "cleanup":
            raise BenchmarkFailure("cleanup failed")


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("benchmark.jvm_diagnostic"))
        self.module = importlib.import_module("benchmark.jvm_diagnostic")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name)
        patcher = patch.object(self.module, "CACHE_ROOT", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = self.cache / "run"
        self.environments = []
        self.metadata = {"source_commit": "a" * 40, "source_tree": "b" * 40}

    def run_study(self, fail=None, count=None):
        def factory(root):
            env = Environment(root, fail)
            self.environments.append(env)
            return env

        return self.module.run_study(
            self.output,
            factory,
            metadata=self.metadata,
            contract=lambda *a, **k: 2 * len(load_cases()) if count is None else count,
        )

    def test_predeclared_order_windows_and_clean_projects(self):
        result = self.run_study()
        expected = [
            "java-spring-boot",
            "node-fastify",
            "go-gin",
            "node-fastify",
            "go-gin",
            "java-spring-boot",
            "go-gin",
            "java-spring-boot",
            "node-fastify",
        ]
        self.assertEqual([a["implementation"] for a in result["attempts"]], expected)
        self.assertEqual(len(self.environments), 9)
        for env in self.environments:
            self.assertEqual(env.events[-1], "cleanup")
            self.assertEqual(
                env.events[2:-1],
                [
                    (endpoint, 5 if i == 0 else 30, i)
                    for endpoint in ("/json", "/db/42", "/cpu")
                    for i in range(5)
                ],
            )
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["official"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result["mode"], "jvm-warmup-diagnostic")
        self.assertEqual(result, json.loads((self.output / "diagnostic.json").read_text()))
        self.assertTrue((self.output / "checksums.json").is_file())
        from benchmark.report import validate_report

        with self.assertRaises(BenchmarkFailure):
            validate_report(result)

    def test_failure_and_interruption_journal_before_cleanup_no_retry(self):
        for stage in ("build", "measure", "cleanup", "interrupt"):
            with self.subTest(stage=stage):
                self.output = self.cache / stage
                self.environments = []
                with self.assertRaises((BenchmarkFailure, KeyboardInterrupt)):
                    self.run_study(fail=stage)
                result = json.loads((self.output / "diagnostic.json").read_text())
                self.assertEqual(result["status"], "failed")
                self.assertEqual(len(self.environments), 1)
                self.assertEqual(self.environments[0].events[-1], "cleanup")
                self.assertEqual(result["attempts"][0]["status"], "failed")
                self.assertTrue(all(a["status"] == "not-started" for a in result["attempts"][1:]))
                self.assertTrue((self.output / "checksums.json").is_file())

    def test_contract_count_fail_closed_without_load(self):
        with self.assertRaises(BenchmarkFailure):
            self.run_study(count=True)
        self.assertEqual(len(self.environments[0].events), 3)

    def test_no_overwrite_or_output_escape(self):
        self.run_study()
        before = (self.output / "diagnostic.json").read_bytes()
        with self.assertRaises(BenchmarkFailure):
            self.run_study()
        self.assertEqual(before, (self.output / "diagnostic.json").read_bytes())
        for path in (self.cache / ".." / "escape", self.cache):
            with self.assertRaises(BenchmarkFailure):
                self.module.validate_directory(path)
        (self.cache / "linked").symlink_to(self.cache, target_is_directory=True)
        with self.assertRaises(BenchmarkFailure):
            self.module.validate_directory(self.cache / "linked" / "run2")

    def test_provisional_stability_rules_include_trend_and_missing_data(self):
        def windows(rps, p95=(2, 2, 2, 2)):
            return [{"requests_per_second": r, "p95_response_time_ms": p} for r, p in zip(rps, p95)]

        analyze = self.module.analyze_windows
        self.assertTrue(analyze(windows([100, 101, 100, 101]))["five_second_supported"])
        self.assertFalse(analyze(windows([90, 101, 100, 101]))["five_second_supported"])
        self.assertFalse(analyze(windows([100, 100, 101, 102]))["late_stable"])
        self.assertFalse(analyze(windows([100, 90, 110, 100]))["late_stable"])
        self.assertFalse(analyze(windows([100, 101, 100, 101], [2, 2, 3, 2]))["late_stable"])
        with self.assertRaises(BenchmarkFailure):
            analyze(windows([100, 100, 100]))
        with self.assertRaises(BenchmarkFailure):
            analyze(windows([100, float("nan"), 100, 100]))
