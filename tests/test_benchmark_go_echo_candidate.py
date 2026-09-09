"""Issue #29 boundary: register Go / Echo without changing the active cohort."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GoEchoCandidateTests(unittest.TestCase):
    def test_go_echo_is_registered_without_expanding_four_stack_v1(self):
        registry = json.loads((ROOT / "benchmark" / "implementations.json").read_text())
        implementations = {entry["id"]: entry for entry in registry["implementations"]}

        self.assertIn("go-echo", implementations)
        echo = implementations["go-echo"]
        self.assertEqual(echo["language"], "Go")
        self.assertEqual(echo["framework"], "Echo")
        self.assertEqual(echo["display_name"], "Go / Echo")
        self.assertEqual(echo["source_path"], "apps/go-echo")
        self.assertEqual(echo["version_fields"], ["go", "echo", "pgx"])
        self.assertEqual(echo["acceptance_test"], "tests/test_go_echo_service.py")
        self.assertIsNone(echo["failure_test"])

        self.assertEqual(registry["active_cohort"], "four-stack-v1")
        self.assertEqual(
            registry["cohorts"]["four-stack-v1"]["members"],
            ["go-gin", "rust-actix", "node-fastify", "python-fastapi"],
        )


if __name__ == "__main__":
    unittest.main()
