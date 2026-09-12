"""Issue #32 contract for the Python / Flask candidate."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "python-flask"


class PythonFlaskCandidateTests(unittest.TestCase):
    def test_flask_profile_is_explicit_and_single_process(self):
        self.assertEqual((APP / ".python-version").read_text().strip(), "3.14.7")
        requirements = set((APP / "requirements.in").read_text().splitlines())
        self.assertIn("flask==3.1.3", requirements)
        self.assertIn("waitress==3.0.2", requirements)
        self.assertIn("psycopg==3.3.5", requirements)
        self.assertIn("psycopg-pool==3.3.1", requirements)
        server = (APP / "benchmark_api" / "server.py").read_text()
        self.assertIn("threads=1", server)
        self.assertIn("create_server", server)
        self.assertNotIn("gunicorn", server.lower())

    def test_flask_is_registered_without_expanding_official_cohort(self):
        registry = json.loads((ROOT / "benchmark" / "implementations.json").read_text())
        by_id = {entry["id"]: entry for entry in registry["implementations"]}
        flask = by_id["python-flask"]
        self.assertEqual(flask["display_name"], "Python / Flask")
        self.assertEqual(flask["source_path"], "apps/python-flask")
        self.assertEqual(registry["active_cohort"], "four-stack-v1")
        self.assertNotIn(
            "python-flask", registry["cohorts"]["four-stack-v1"]["members"]
        )


if __name__ == "__main__":
    unittest.main()
