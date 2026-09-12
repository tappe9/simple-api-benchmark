"""Registry boundaries and historical-cohort compatibility regressions."""

import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from registry_fixtures import expanded_report, explicit_report, extended_registry
from test_benchmark_publication import synthetic_report

from benchmark.results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]


class RegistryBoundaryTests(unittest.TestCase):
    def test_authoritative_registry_contains_only_implemented_stacks(self):
        path = ROOT / "benchmark" / "implementations.json"
        self.assertTrue(path.is_file(), "authoritative implementation registry is missing")
        registry = json.loads(path.read_text())
        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual(
            [entry["id"] for entry in registry["implementations"]],
            [
                "go-gin",
                "go-echo",
                "rust-actix",
                "rust-axum",
                "node-fastify",
                "node-express",
                "python-fastapi",
                "python-flask",
            ],
        )

    def test_report_validation_does_not_import_measurement_orchestration(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import benchmark.report; import sys; print('benchmark.run' in sys.modules)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            completed.stdout.strip(),
            "False",
            "report validation must not depend on the measurement runner",
        )

    def test_frontend_uses_a_generated_registry_projection(self):
        self.assertTrue(
            (ROOT / "site" / "registry.mjs").is_file(),
            "deterministic frontend registry projection is missing",
        )


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("benchmark.registry"), "registry policy is missing"
        )
        from benchmark import registry

        self.registry = registry
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = synthetic_report(self.root)

    def test_legacy_cohort_is_explicit_and_independent_of_active_members(self):
        from benchmark.report import validate_report

        legacy = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")
        with patch.object(self.registry, "REGISTRY", extended_registry()):
            self.assertEqual(len(self.registry.active_members()), 8)
            self.assertEqual(self.registry.report_members(self.report), legacy)
            validate_report(self.report)
            for path in (ROOT / "results").rglob("*.json"):
                validate_report(json.loads(path.read_bytes()))

    def test_explicit_current_and_extended_cohorts_validate_and_audit_raw(self):
        from benchmark.report import audit_raw, validate_report

        current = explicit_report(self.report)
        validate_report(current)
        audit_raw(current, self.root)
        expanded = expanded_report(self.report, self.root)
        with self.assertRaises(BenchmarkFailure):
            validate_report(expanded)
        with patch.object(self.registry, "REGISTRY", extended_registry()):
            validate_report(expanded)
            audit_raw(expanded, self.root)
            self.assertEqual(len(self.registry.report_members(expanded)), 8)

    def test_invalid_identity_partial_order_endpoints_and_versions_fail_closed(self):
        from benchmark.report import validate_report

        valid = expanded_report(self.report)
        mutations = []

        def changed(path, value):
            report = copy.deepcopy(valid)
            target = report
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            mutations.append(report)

        changed(("benchmark", "cohort"), "unknown-v1")
        changed(("benchmark", "cohort"), "__proto__")
        changed(("benchmark", "cohort"), [])
        changed(("benchmark", "definition"), "different-v1")
        changed(("benchmark",), {**valid["benchmark"], "members": ["go-gin"]})
        changed(("schema_version",), True)
        changed(("schema_version",), 3)
        changed(("implementations",), valid["implementations"][:-1])
        changed(("implementations",), list(reversed(valid["implementations"])))
        changed(("implementations", 1, "implementation"), "go-gin")
        changed(("implementations", 1, "implementation"), "unknown-id")
        changed(("implementations", 7, "endpoints"), valid["implementations"][7]["endpoints"][:-1])
        changed(
            ("implementations", 7, "endpoints"),
            list(reversed(valid["implementations"][7]["endpoints"])),
        )
        changed(("metadata", "versions", "synthetic-python"), {"runtime": "1.2.3"})
        changed(("metadata", "versions", "synthetic-python", "runtime"), None)
        changed(("metadata", "versions"), {**valid["metadata"]["versions"], "unknown": {}})
        changed(("official",), False)
        changed(("mode",), "smoke")
        missing = copy.deepcopy(valid)
        del missing["benchmark"]
        mutations.append(missing)
        legacy = copy.deepcopy(valid)
        legacy["schema_version"] = 1
        mutations.append(legacy)
        del legacy["benchmark"]
        mutations.append(copy.deepcopy(legacy))
        with patch.object(self.registry, "REGISTRY", extended_registry()):
            for index, report in enumerate(mutations):
                with self.subTest(index=index), self.assertRaises(BenchmarkFailure):
                    validate_report(report)

    def test_readme_uses_selected_cohort_and_escapes_registry_labels(self):
        from benchmark.generate_readme import render

        data = extended_registry()
        data["implementations"][-1]["display_name"] = "<script>alert(1)</script> | fixture"
        report = expanded_report(self.report)
        with patch.object(self.registry, "REGISTRY", data):
            for locale in ("en", "ja"):
                output = render(report, locale)
                self.assertIn("&lt;script&gt;", output)
                self.assertNotIn("<script>", output)
                self.assertIn("\\| fixture", output)
                self.assertEqual(sum(line.startswith("| ") for line in output.splitlines()), 26)
                self.assertEqual(
                    sum(line.startswith("| ") for line in render(self.report, locale).splitlines()),
                    14,
                )

    def test_registry_rejects_duplicates_unknown_members_and_invalid_paths(self):
        valid = self.registry.load_registry()
        mutations = []
        for field, value in (("schema_version", True), ("active_cohort", "unknown-v1")):
            data = copy.deepcopy(valid)
            data[field] = value
            mutations.append(data)
        data = copy.deepcopy(valid)
        data["implementations"].append(copy.deepcopy(data["implementations"][0]))
        mutations.append(data)
        for field, value in (
            ("id", "../escape"),
            ("source_path", "../escape"),
            ("acceptance_test", "$(touch bad)"),
            ("version_fields", []),
            ("version_fields", ["go", "go"]),
        ):
            data = copy.deepcopy(valid)
            data["implementations"][0][field] = value
            mutations.append(data)
        for members in (["unknown-id"], ["go-gin", "go-gin"], []):
            data = copy.deepcopy(valid)
            data["cohorts"]["four-stack-v1"]["members"] = members
            mutations.append(data)
        for index, data in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(BenchmarkFailure):
                self.registry.validate_registry(data)

    def test_generated_projections_are_deterministic_and_drift_is_rejected(self):
        outputs = self.registry.generated_files()
        self.assertEqual(outputs, self.registry.generated_files())
        self.assertEqual(set(outputs), {"site/registry.mjs", "benchmark/implementations.mk"})
        self.registry.check_generated()
        for name, content in outputs.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.registry.check_generated(self.root)
        for name in outputs:
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b"drift")
            with self.subTest(name=name), self.assertRaises(BenchmarkFailure):
                self.registry.check_generated(self.root)
            path.write_bytes(original)
        self.registry.check_generated(self.root)
        self.registry.check_sources()

    def test_generated_projection_cannot_be_read_through_a_symlinked_directory(self):
        outputs = self.registry.generated_files()
        outside = self.root / "outside"
        for name, content in outputs.items():
            path = (outside if name.startswith("site/") else self.root) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.root / "site").symlink_to(outside / "site", target_is_directory=True)
        with self.assertRaises(BenchmarkFailure):
            self.registry.check_generated(self.root)

    def test_version_extraction_must_cover_registered_stacks(self):
        from benchmark.environment import pinned_versions

        actual = pinned_versions()
        self.assertEqual(tuple(actual), self.registry.active_members())
        for identifier, versions in actual.items():
            self.assertTrue(
                set(self.registry.implementation(identifier)["version_fields"]) <= set(versions)
            )
        with (
            patch.object(self.registry, "REGISTRY", extended_registry()),
            self.assertRaises(BenchmarkFailure),
        ):
            pinned_versions()

    def test_runner_emits_explicit_cohort_and_keeps_smoke_non_publishable(self):
        from test_benchmark_runner import Environment

        from benchmark import run
        from benchmark.report import validate_report

        output = self.root / "result.json"
        environment = Environment()
        with (
            patch.object(self.registry, "REGISTRY", extended_registry()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = run.run_benchmark(
                environment,
                copy.deepcopy(run.PROFILE),
                output,
                metadata={},
                contract=environment.contract,
                smoke=True,
            )
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(
                result["benchmark"], {"definition": "simple-api-v1", "cohort": "synthetic-eight-v1"}
            )
            self.assertEqual(
                [item["implementation"] for item in result["implementations"]],
                list(self.registry.active_members()),
            )
            self.assertFalse(output.exists())
            with self.assertRaises(BenchmarkFailure):
                validate_report(result)


if __name__ == "__main__":
    unittest.main()
