"""Registry boundaries and historical-cohort compatibility regressions."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RegistryBoundaryTests(unittest.TestCase):
    def test_authoritative_registry_contains_only_implemented_stacks(self):
        path = ROOT / "benchmark" / "implementations.json"
        self.assertTrue(path.is_file(), "authoritative implementation registry is missing")
        registry = json.loads(path.read_text())
        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual(
            [entry["id"] for entry in registry["implementations"]],
            ["go-gin", "rust-actix", "node-fastify", "python-fastapi"],
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


if __name__ == "__main__":
    unittest.main()
