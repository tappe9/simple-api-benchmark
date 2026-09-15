"""Rust / Axum registration preserves legacy identity across cohort activation."""

import json
import unittest
from pathlib import Path

from benchmark import environment
from benchmark.registry import active_members, implementation, implementation_ids, report_members
from benchmark.report import validate_report

ROOT = Path(__file__).resolve().parents[1]
LEGACY_MEMBERS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


class AxumRegistrationTests(unittest.TestCase):
    def test_axum_is_registered_with_independent_source_and_versions(self):
        self.assertIn("rust-axum", implementation_ids())
        spec = implementation("rust-axum")
        self.assertEqual(spec["source_path"], "apps/rust-axum")
        self.assertEqual(spec["acceptance_test"], "tests/test_rust_axum_service.py")
        self.assertEqual(spec["failure_test"], "tests/test_rust_axum_acceptance.py")
        self.assertEqual(
            spec["version_fields"], ["rust", "axum", "tokio", "sqlx", "serde", "serde_json"]
        )

    def test_registered_versions_include_axum_and_official_versions_follow_active_cohort(self):
        self.assertTrue(callable(getattr(environment, "registered_pinned_versions", None)))
        versions = environment.registered_pinned_versions()
        self.assertEqual(set(versions), set(implementation_ids()))
        self.assertEqual(set(environment.pinned_versions()), set(active_members()))
        for name in ("rust", "sqlx", "serde", "serde_json"):
            self.assertEqual(versions["rust-axum"][name], versions["rust-actix"][name])
        self.assertEqual(versions["rust-axum"]["axum"], "0.8.9")
        self.assertEqual(versions["rust-axum"]["tokio"], "1.53.1")

    def test_legacy_cohort_is_frozen_and_publication_has_its_own_complete_identity(self):
        registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        self.assertEqual(tuple(registry["cohorts"]["four-stack-v1"]["members"]), LEGACY_MEMBERS)
        report = json.loads((ROOT / "results/latest.json").read_text())
        validate_report(report)
        self.assertEqual(
            tuple(row["implementation"] for row in report["implementations"]),
            report_members(report),
        )


if __name__ == "__main__":
    unittest.main()
