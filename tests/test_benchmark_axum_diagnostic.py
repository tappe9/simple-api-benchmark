"""Axum-only diagnostics must never become an official or partial publication."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_runner import Environment

from benchmark.environment import registered_pinned_versions
from benchmark.healthcheck import EXTERNAL_READINESS
from benchmark.report import validate_report
from benchmark.results import BenchmarkFailure


class AxumDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("benchmark.axum_diagnostic"),
            "Axum needs an independent non-publishing diagnostic",
        )
        self.module = importlib.import_module("benchmark.axum_diagnostic")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / ".cache" / "axum-diagnostic"
        self.cache.mkdir(parents=True)
        self.output = self.cache / "diagnostic.json"
        self.output.write_bytes(b"previous diagnostic")
        self.published = self.root / "results" / "latest.json"
        self.published.parent.mkdir()
        self.published.write_bytes(b"previous official result")
        patcher = patch.object(self.module, "CACHE_ROOT", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.metadata = {
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "versions": {"rust-axum": registered_pinned_versions()["rust-axum"]},
        }

    def environment(self, fail=None):
        result = Environment(fail)
        result.health_policy = EXTERNAL_READINESS
        result.connections = 2
        result.request_timeout = 15
        result.readiness = {"attempts": 1, "duration_seconds": 0.1}
        return result

    def run_diagnostic(self, environment):
        return self.module.run_diagnostic(
            environment,
            self.output,
            metadata=self.metadata,
            contract=environment.contract,
        )

    def test_only_axum_uses_fixed_short_profile_and_cleans_before_writing(self):
        environment = self.environment()
        original_cleanup = environment.cleanup

        def cleanup():
            self.assertEqual(self.output.read_bytes(), b"previous diagnostic")
            original_cleanup()
            environment.readiness = None

        with patch.object(environment, "cleanup", side_effect=cleanup):
            result = self.run_diagnostic(environment)
        self.assertEqual(environment.events.count("build"), 1)
        self.assertEqual(environment.events.count("cleanup"), 1)
        measured = [value for value in environment.events if type(value) is tuple]
        self.assertEqual(
            measured,
            [
                ("rust-axum", endpoint, 1 if index == 0 else 2, index)
                for endpoint in ("/json", "/db/42", "/cpu")
                for index in (0, 1, 2, 3)
            ],
        )
        self.assertEqual(environment.measures, 9)
        self.assertEqual(result["readiness"], {"attempts": 1, "duration_seconds": 0.1})
        self.assertIsNone(environment.active)
        self.assertFalse(result["official"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result["mode"], "axum-diagnostic")
        self.assertEqual(result["implementation"], "rust-axum")
        self.assertEqual(result["metadata"]["versions"], self.metadata["versions"])
        self.assertEqual(result, json.loads(self.output.read_bytes()))
        self.assertEqual(self.published.read_bytes(), b"previous official result")
        with self.assertRaises(BenchmarkFailure):
            validate_report(result)

    def test_every_failure_cleans_and_preserves_previous_diagnostic_and_official_result(self):
        for stage in ("build", "startup", "contract", "state", "warmup", "measurement", "metric", "cleanup"):
            environment = self.environment(stage)
            with self.subTest(stage=stage), self.assertRaisesRegex(BenchmarkFailure, stage):
                self.run_diagnostic(environment)
            self.assertEqual(environment.events.count("cleanup"), 1)
            self.assertIsNone(environment.active)
            self.assertEqual(self.output.read_bytes(), b"previous diagnostic")
            self.assertEqual(self.published.read_bytes(), b"previous official result")

    def test_interruption_cleans_without_a_partial_result(self):
        environment = self.environment()
        with patch.object(environment, "measure", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_diagnostic(environment)
        self.assertEqual(environment.events.count("cleanup"), 1)
        self.assertEqual(self.output.read_bytes(), b"previous diagnostic")

    def test_invalid_contract_count_prevents_load(self):
        environment = self.environment()
        with patch.object(environment, "contract", return_value=True):
            with self.assertRaisesRegex(BenchmarkFailure, "shared contract"):
                self.run_diagnostic(environment)
        self.assertEqual(environment.measures, 0)
        self.assertEqual(environment.events[-1], "cleanup")

    def test_wrong_policy_or_profile_prevents_startup(self):
        for field, value in (("health_policy", "container-healthcheck"), ("connections", 50), ("request_timeout", 1)):
            environment = self.environment()
            setattr(environment, field, value)
            with self.subTest(field=field), self.assertRaises(BenchmarkFailure):
                self.run_diagnostic(environment)
            self.assertNotIn("build", environment.events)
            self.assertEqual(self.output.read_bytes(), b"previous diagnostic")

    def test_output_and_symlinks_cannot_reach_published_files(self):
        for path in (self.published, self.cache / ".." / "outside.json"):
            with self.subTest(path=path), self.assertRaises(BenchmarkFailure):
                self.module.validate_output_path(path)
        linked = self.cache / "linked"
        linked.symlink_to(self.published.parent, target_is_directory=True)
        with self.assertRaises(BenchmarkFailure):
            self.module.validate_output_path(linked / "latest.json")
        self.output.unlink()
        self.output.symlink_to(self.published)
        with self.assertRaises(BenchmarkFailure):
            self.run_diagnostic(self.environment())
        self.assertEqual(self.published.read_bytes(), b"previous official result")


if __name__ == "__main__":
    unittest.main()
