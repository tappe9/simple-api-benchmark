"""Real cohort compatibility; synthetic data stays in isolated temporary repositories."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_benchmark_publication_manifest as manifest_tests
import test_benchmark_registry_publication as publication_tests
from registry_fixtures import EIGHT_MEMBERS, explicit_report, real_eight_report
from test_benchmark_publication import context, synthetic_report
from test_benchmark_runner import Environment

from benchmark import environment, generate_readme, readme_charts, registry, run
from benchmark.healthcheck import EXTERNAL_READINESS
from benchmark.report import audit_raw, comparison_compatibility, validate_report
from benchmark.results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]
LEGACY_MEMBERS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


class EightStackRegistryTests(unittest.TestCase):
    def test_active_cohort_and_version_projection_use_all_eight_registered_stacks(self):
        self.assertEqual(
            registry.active_benchmark(),
            {"definition": "simple-api-v1", "cohort": "eight-stack-v1"},
        )
        self.assertEqual(registry.active_members(), EIGHT_MEMBERS)
        self.assertEqual(tuple(environment.pinned_versions()), EIGHT_MEMBERS)

    def test_default_runner_measures_the_approved_cohort_without_registry_overrides(self):
        subject = Environment()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "candidate.json"
            result = run.run_benchmark(
                subject,
                run.load_config(),
                output,
                metadata={},
                contract=subject.contract,
                health_policy=EXTERNAL_READINESS,
            )
            self.assertEqual(
                result["benchmark"], {"definition": "simple-api-v1", "cohort": "eight-stack-v1"}
            )
            self.assertEqual(
                tuple(backend["implementation"] for backend in result["implementations"]),
                EIGHT_MEMBERS,
            )
            self.assertEqual(subject.measures, 72)
            self.assertEqual(subject.events.count("cleanup"), 8)
            self.assertIsNone(subject.active)
            self.assertEqual(json.loads(output.read_bytes()), result)
            self.assertIs(result["official"], False)

    def test_real_eight_stack_cohort_is_registered_in_frozen_order(self):
        data = registry.load_registry()
        self.assertIn("eight-stack-v1", data["cohorts"])
        self.assertEqual(
            data["cohorts"]["eight-stack-v1"],
            {"definition": "simple-api-v1", "members": list(EIGHT_MEMBERS)},
        )
        registry.check_generated()

    def test_legacy_membership_and_order_are_unchanged(self):
        self.assertEqual(
            registry.load_registry()["cohorts"]["four-stack-v1"],
            {"definition": "simple-api-v1", "members": list(LEGACY_MEMBERS)},
        )


class EightStackReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.legacy = synthetic_report(self.root)
        self.report = real_eight_report(self.legacy, self.root)

    def test_complete_real_cohorts_validate_and_audit_without_a_fixture_registry(self):
        for report in (self.legacy, explicit_report(self.legacy), self.report):
            with self.subTest(schema=report["schema_version"], cohort=report.get("benchmark")):
                validate_report(report)
                audit_raw(report, self.root)
        self.assertEqual(registry.report_members(self.report), EIGHT_MEMBERS)
        self.assertEqual(
            sum(len(e["runs"]) for b in self.report["implementations"] for e in b["endpoints"]), 72
        )
        self.assertNotEqual(
            comparison_compatibility(self.report), comparison_compatibility(self.legacy)
        )

    def test_each_member_endpoint_version_and_provenance_field_is_required(self):
        for original in (self.legacy, explicit_report(self.legacy), self.report):
            validate_report(
                original
            )  # Negative cases cannot pass merely because the cohort is unknown.
            mutations = []
            for index, backend in enumerate(original["implementations"]):
                identifier = backend["implementation"]
                missing = copy.deepcopy(original)
                missing["implementations"].pop(index)
                mutations.append((f"missing {identifier}", missing))
                for replacement in (
                    "unknown-stack",
                    original["implementations"][(index + 1) % len(original["implementations"])][
                        "implementation"
                    ],
                ):
                    bad = copy.deepcopy(original)
                    bad["implementations"][index]["implementation"] = replacement
                    mutations.append((f"identity {identifier}", bad))
                for endpoint in range(3):
                    bad = copy.deepcopy(original)
                    bad["implementations"][index]["endpoints"].pop(endpoint)
                    mutations.append((f"endpoint {identifier} {endpoint}", bad))
                for field in registry.implementation(identifier)["version_fields"]:
                    bad = copy.deepcopy(original)
                    del bad["metadata"]["versions"][identifier][field]
                    mutations.append((f"version {identifier} {field}", bad))
            for field in ("source_commit", "source_tree", "github", "runner", "versions"):
                bad = copy.deepcopy(original)
                del bad["metadata"][field]
                mutations.append((f"provenance {field}", bad))
            for mutate in (
                lambda r: r["implementations"].reverse(),
                lambda r: r["implementations"][0]["endpoints"].reverse(),
                lambda r: r["implementations"][-1]["endpoints"][-1]["runs"].pop(),
                lambda r: r["metadata"]["versions"].update({"unknown-stack": {}}),
            ):
                bad = copy.deepcopy(original)
                mutate(bad)
                mutations.append(("order/completeness", bad))
            for label, bad in mutations:
                with (
                    self.subTest(cohort=original.get("benchmark"), mutation=label),
                    self.assertRaises(BenchmarkFailure),
                ):
                    validate_report(bad)
        bad = copy.deepcopy(self.report)
        del bad["metadata"]["api_health_policy"]
        with self.assertRaises(BenchmarkFailure):
            validate_report(bad)
        for cohort in ("four-stack-v1", "unknown-v1"):
            bad = copy.deepcopy(self.report)
            bad["benchmark"]["cohort"] = cohort
            with self.subTest(cohort=cohort), self.assertRaises(BenchmarkFailure):
                validate_report(bad)

    def test_active_cohort_switch_does_not_reinterpret_historical_results(self):
        data = registry.load_registry()
        self.assertIn("eight-stack-v1", data["cohorts"])
        data["active_cohort"] = "eight-stack-v1"
        with patch.object(registry, "REGISTRY", data):
            self.assertEqual(registry.active_members(), EIGHT_MEMBERS)
            self.assertEqual(tuple(environment.pinned_versions()), EIGHT_MEMBERS)
            for report in (self.legacy, explicit_report(self.legacy), self.report):
                validate_report(report)
                audit_raw(report, self.root)
            for path in (ROOT / "results").rglob("*.json"):
                validate_report(json.loads(path.read_bytes()))

    def test_readme_and_charts_use_the_report_not_the_active_cohort(self):
        for report, members in ((self.legacy, LEGACY_MEMBERS), (self.report, EIGHT_MEMBERS)):
            for locale in ("en", "ja"):
                output = generate_readme.render(report, locale)
                self.assertIn(
                    "four-stack-v1" if members == LEGACY_MEMBERS else "eight-stack-v1", output
                )
                self.assertIn("simple-api-v1", output)
                for identifier in members:
                    self.assertIn(registry.implementation(identifier)["display_name"], output)
                self.assertEqual(
                    sum(line.startswith("| ") for line in output.splitlines()), 2 + 3 * len(members)
                )
            charts = readme_charts.render_charts(report)
            self.assertEqual(len(charts), 3)
            for svg in charts.values():
                for identifier in EIGHT_MEMBERS:
                    label = registry.implementation(identifier)["display_name"]
                    self.assertEqual(label in svg, identifier in members)
        self.assertIn(EXTERNAL_READINESS, generate_readme.render(self.report, "en"))


class EightStackLifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "candidate.json"
        self.output.write_bytes(b"previous verified result")
        data = registry.load_registry()
        self.assertIn("eight-stack-v1", data["cohorts"])
        data["active_cohort"] = "eight-stack-v1"
        patched = patch.object(registry, "REGISTRY", data)
        patched.start()
        self.addCleanup(patched.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def call(self, subject, *, smoke=False):
        return run.run_benchmark(
            subject,
            run.load_config(),
            self.output,
            metadata={},
            contract=subject.contract,
            health_policy=EXTERNAL_READINESS,
            smoke=smoke,
        )

    def test_fixed_profile_performs_72_samples_and_24_warmups_sequentially(self):
        subject = Environment()
        result = self.call(subject)
        measurements = [event for event in subject.events if type(event) is tuple]
        self.assertEqual(
            measurements,
            [
                (identifier, endpoint, 5 if index == 0 else 30, index)
                for identifier in EIGHT_MEMBERS
                for endpoint in ("/json", "/db/42", "/cpu")
                for index in (0, 1, 2, 3)
            ],
        )
        self.assertEqual(subject.measures, 72)
        self.assertEqual(subject.events.count("cleanup"), 8)
        self.assertEqual(
            [b["implementation"] for b in result["implementations"]], list(EIGHT_MEMBERS)
        )
        self.assertFalse(result["official"])
        self.assertEqual(result["metadata"]["api_health_policy"], EXTERNAL_READINESS)

    def test_last_member_failure_or_cleanup_preserves_previous_output(self):
        for failure in ("measurement", "cleanup", "timeout"):
            subject = Environment()
            original_measure = subject.measure
            original_cleanup = subject.cleanup

            def measure(endpoint, duration, index):
                if subject.measures == 71 and index > 0 and failure != "cleanup":
                    raise BenchmarkFailure("injected " + failure)
                return original_measure(endpoint, duration, index)

            def cleanup():
                last = subject.active == EIGHT_MEMBERS[-1]
                original_cleanup()
                if last and failure == "cleanup":
                    raise BenchmarkFailure("injected cleanup")

            with (
                patch.object(subject, "measure", side_effect=measure),
                patch.object(subject, "cleanup", side_effect=cleanup),
            ):
                with (
                    self.subTest(failure=failure),
                    self.assertRaisesRegex(BenchmarkFailure, failure),
                ):
                    self.call(subject)
            self.assertEqual(self.output.read_bytes(), b"previous verified result")
            self.assertIsNone(subject.active)
            self.assertEqual(subject.events.count("cleanup"), 8)

    def test_eight_stack_smoke_never_replaces_output_or_claims_official_status(self):
        result = self.call(Environment(), smoke=True)
        self.assertEqual(len(result["implementations"]), 8)
        self.assertFalse(result["official"])
        self.assertEqual(result["mode"], "smoke")
        self.assertEqual(self.output.read_bytes(), b"previous verified result")
        with self.assertRaises(BenchmarkFailure):
            validate_report(result)


class EightStackPublicationTests(publication_tests.CohortPublicationTests):
    def test_real_eight_stack_atomic_publication_and_incomplete_raw_rejection(self):
        from benchmark import publish

        self.report = real_eight_report(self.report, self.repo)
        validate_report(self.report)
        for index in range(8):
            incomplete = copy.deepcopy(self.report)
            incomplete["implementations"].pop(index)
            with self.subTest(index=index), self.assertRaises(BenchmarkFailure):
                publish.publish(incomplete, self.repo, expected_context=context(self.source))
            self.assertEqual(self.remote_head(), self.source)
        raw = (
            self.repo
            / self.report["metadata"]["artifact_directory"]
            / "python-flask-cpu-run-3.json"
        )
        before = raw.read_bytes()
        raw.write_text("{}")
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.remote_head(), self.source)
        raw.write_bytes(before)
        self.assert_complete_transaction()


class EightStackPagesTrustTests(manifest_tests.PublicationManifestIntegrationTests):
    def setUp(self):
        super().setUp()
        self.report = real_eight_report(self.report, self.repo)


if __name__ == "__main__":
    unittest.main()
