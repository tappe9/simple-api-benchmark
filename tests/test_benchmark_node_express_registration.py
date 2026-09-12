"""Node.js / Express registration must not activate an incomplete official cohort."""

import json
import unittest
from pathlib import Path

from benchmark import environment
from benchmark.registry import active_members, implementation, implementation_ids

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


class ExpressRegistrationTests(unittest.TestCase):
    def test_express_is_registered_without_official_activation(self):
        self.assertIn("node-express", implementation_ids())
        self.assertEqual(active_members(), OFFICIAL)
        spec = implementation("node-express")
        self.assertEqual(spec["source_path"], "apps/node-express")
        self.assertEqual(spec["acceptance_test"], "tests/test_node_express_service.py")
        self.assertEqual(spec["failure_test"], "tests/test_node_express_acceptance.py")
        self.assertEqual(spec["version_fields"], ["node", "express", "pg"])

    def test_registered_versions_include_express_but_official_versions_do_not(self):
        versions = environment.registered_pinned_versions()
        self.assertEqual(set(versions), set(implementation_ids()))
        self.assertEqual(set(environment.pinned_versions()), set(OFFICIAL))
        self.assertEqual(versions["node-express"]["node"], versions["node-fastify"]["node"])
        self.assertEqual(versions["node-express"]["pg"], versions["node-fastify"]["pg"])
        self.assertEqual(versions["node-express"]["express"], "5.2.1")

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
