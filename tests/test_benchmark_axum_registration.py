"""Rust / Axum registration must not activate an incomplete official cohort."""

import json
import unittest
from pathlib import Path

from benchmark import environment
from benchmark.registry import active_members, implementation, implementation_ids

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


class AxumRegistrationTests(unittest.TestCase):
    def test_axum_is_registered_without_official_activation(self):
        self.assertIn("rust-axum", implementation_ids())
        self.assertEqual(active_members(), OFFICIAL)
        spec = implementation("rust-axum")
        self.assertEqual(spec["source_path"], "apps/rust-axum")
        self.assertEqual(spec["acceptance_test"], "tests/test_rust_axum_service.py")
        self.assertEqual(spec["failure_test"], "tests/test_rust_axum_acceptance.py")
        self.assertEqual(
            spec["version_fields"], ["rust", "axum", "tokio", "sqlx", "serde", "serde_json"]
        )

    def test_registered_versions_include_axum_but_official_versions_do_not(self):
        self.assertTrue(callable(getattr(environment, "registered_pinned_versions", None)))
        versions = environment.registered_pinned_versions()
        self.assertEqual(set(versions), set(implementation_ids()))
        self.assertEqual(set(environment.pinned_versions()), set(OFFICIAL))
        for name in ("rust", "sqlx", "serde", "serde_json"):
            self.assertEqual(versions["rust-axum"][name], versions["rust-actix"][name])
        self.assertEqual(versions["rust-axum"]["axum"], "0.8.9")
        self.assertEqual(versions["rust-axum"]["tokio"], "1.53.1")

    def test_official_cohort_and_publication_remain_four_stacks(self):
        registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        self.assertEqual(registry["active_cohort"], "four-stack-v1")
        self.assertEqual(tuple(registry["cohorts"]["four-stack-v1"]["members"]), OFFICIAL)
        report = json.loads((ROOT / "results/latest.json").read_text())
        self.assertEqual(report["benchmark"]["cohort"], "four-stack-v1")
        self.assertEqual(
            tuple(row["implementation"] for row in report["implementations"]), OFFICIAL
        )


if __name__ == "__main__":
    unittest.main()
