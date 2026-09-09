import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CIHelperTests(unittest.TestCase):
    def run_ci(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "benchmark.ci", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_matrix_cli_emits_registry_implementations_in_order(self):
        registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        result = self.run_ci("matrix")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"include": [{"implementation": spec["id"]} for spec in registry["implementations"]]},
        )

    def test_require_success_accepts_only_all_success(self):
        result = self.run_ci(
            "require-success",
            "plan=success",
            "shared=success",
            "implementation=success",
            "smoke=success",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_require_success_rejects_failure_cancelled_and_skipped(self):
        for state in ("failure", "cancelled", "skipped"):
            with self.subTest(state=state):
                result = self.run_ci(
                    "require-success",
                    "plan=success",
                    "shared=success",
                    f"implementation={state}",
                    "smoke=success",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"implementation={state}", result.stderr)


if __name__ == "__main__":
    unittest.main()
