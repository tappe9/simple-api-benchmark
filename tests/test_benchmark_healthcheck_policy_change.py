"""Approved Issue #23 contracts for official health-policy provenance and compatibility."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_benchmark_publication import SOURCE, context, synthetic_report
from test_benchmark_runner import Environment

from benchmark import healthcheck, official, report, run
from benchmark.registry import active_benchmark
from benchmark.results import BenchmarkFailure


class ProvenanceCompatibilityTests(unittest.TestCase):
    def test_run_report_records_the_environment_health_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "latest.json"
            environment = Environment()
            environment.health_policy = healthcheck.EXTERNAL_READINESS
            value = run.run_benchmark(
                environment,
                run.load_config(),
                output,
                metadata={"source_commit": "fixture-only"},
                contract=environment.contract,
            )
        self.assertIn("api_health_policy", value["metadata"])
        self.assertEqual(
            value["metadata"]["api_health_policy"],
            healthcheck.EXTERNAL_READINESS,
        )

    def test_legacy_missing_policy_is_container_healthcheck_only(self):
        reader = getattr(report, "api_health_policy", None)
        self.assertIsNotNone(reader, "report policy resolver is required")
        with tempfile.TemporaryDirectory() as directory:
            legacy = synthetic_report(Path(directory))
        self.assertEqual(reader(legacy), healthcheck.CONTAINER_HEALTHCHECK)

    def test_schema_v2_requires_policy_and_new_policy_is_not_legacy_compatible(self):
        resolver = getattr(report, "api_health_policy", None)
        compatibility = getattr(report, "comparison_compatibility", None)
        self.assertIsNotNone(resolver, "report policy resolver is required")
        self.assertIsNotNone(compatibility, "comparison compatibility key is required")
        with tempfile.TemporaryDirectory() as directory:
            legacy = synthetic_report(Path(directory))
        current = copy.deepcopy(legacy)
        current["schema_version"] = 2
        current["benchmark"] = active_benchmark()
        current["metadata"]["api_health_policy"] = healthcheck.EXTERNAL_READINESS
        self.assertEqual(resolver(current), healthcheck.EXTERNAL_READINESS)
        self.assertNotEqual(compatibility(legacy), compatibility(current))

        missing = copy.deepcopy(current)
        del missing["metadata"]["api_health_policy"]
        with self.assertRaises(BenchmarkFailure):
            resolver(missing)


class LocalPolicyTests(unittest.TestCase):
    def test_local_benchmark_selects_external_readiness_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_environment = Mock()
            fake_environment.artifacts = root / ".cache/benchmark/sab-benchmark-test"
            factory = Mock(return_value=fake_environment)
            candidate = {"metadata": {}, "implementations": []}
            with (
                patch.object(run, "ROOT", root),
                patch.object(run, "load_config", return_value=copy.deepcopy(run.PROFILE)),
                patch("benchmark.environment.DockerEnvironment", factory),
                patch("benchmark.environment.provenance", return_value={}),
                patch("benchmark.install_oha.ensure_oha", return_value=Path("/fake/oha")),
                patch.object(run, "run_benchmark", return_value=candidate) as benchmark,
            ):
                self.assertEqual(run.main([]), 0)

            factory.assert_called_once_with(
                Path("/fake/oha"),
                root / ".cache/benchmark",
                compose="docker compose",
                connections=run.PROFILE["connections"],
                request_timeout=run.PROFILE["request_timeout_seconds"],
                health_policy=healthcheck.EXTERNAL_READINESS,
            )
            self.assertEqual(
                benchmark.call_args.kwargs["health_policy"],
                healthcheck.EXTERNAL_READINESS,
            )


class OfficialPolicyTests(unittest.TestCase):
    def test_official_runner_selects_external_readiness_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".cache/official").mkdir(parents=True)
            fake_environment = Mock()
            fake_environment.artifacts = root / ".cache/official/raw/sab-benchmark-test"
            factory = Mock(return_value=fake_environment)
            candidate = {
                "metadata": {"source_commit": SOURCE},
                "implementations": [],
            }
            with (
                patch.object(official, "ROOT", root),
                patch.object(official, "trusted_context", return_value=context()),
                patch.object(official, "ensure_oha", return_value=Path("/fake/oha")),
                patch.object(
                    official,
                    "provenance",
                    return_value={"source_commit": SOURCE},
                ),
                patch.object(official, "runner_metadata", return_value={}),
                patch.object(official, "execute", return_value="synthetic-version"),
                patch.object(official, "DockerEnvironment", factory),
                patch.object(official, "run_benchmark", return_value=candidate) as benchmark,
                patch.object(official, "validate_report"),
                patch.object(official, "audit_raw"),
                patch.object(official, "atomic_json"),
            ):
                self.assertEqual(official.main(), 0)

            factory.assert_called_once_with(
                Path("/fake/oha"),
                root / ".cache/official/raw",
                health_policy=healthcheck.EXTERNAL_READINESS,
            )
            self.assertEqual(
                benchmark.call_args.kwargs["health_policy"],
                healthcheck.EXTERNAL_READINESS,
            )


if __name__ == "__main__":
    unittest.main()
