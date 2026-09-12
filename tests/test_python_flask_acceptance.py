"""Static and failure-oriented acceptance gates for Python / Flask."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "python-flask"


class PythonFlaskAcceptanceTests(unittest.TestCase):
    def test_approved_wsgi_profile_is_pinned(self):
        self.assertEqual((APP / ".python-version").read_text().strip(), "3.14.7")
        requirements = set((APP / "requirements.in").read_text().splitlines())
        self.assertIn("flask==3.1.3", requirements)
        self.assertIn("waitress==3.0.2", requirements)
        self.assertIn("psycopg==3.3.5", requirements)
        self.assertIn("psycopg-binary==3.3.5", requirements)
        self.assertIn("psycopg-pool==3.3.1", requirements)
        server = (APP / "benchmark_api" / "server.py").read_text()
        self.assertIn("threads=1", server)
        self.assertIn("create_server", server)
        self.assertNotIn("gunicorn", server.lower())

    def test_pool_and_container_limits_are_not_weakened(self):
        database = (APP / "benchmark_api" / "database.py").read_text()
        self.assertIn('"max_size": 10', database)
        dockerfile = (APP / "Dockerfile").read_text()
        self.assertEqual(dockerfile.count("python:3.14.7-slim-bookworm@sha256:"), 2)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "benchmark_api.server"]', dockerfile)

    def test_registration_does_not_change_official_cohort(self):
        registry = json.loads((ROOT / "benchmark" / "implementations.json").read_text())
        self.assertEqual(registry["active_cohort"], "four-stack-v1")
        self.assertNotIn(
            "python-flask", registry["cohorts"]["four-stack-v1"]["members"]
        )
        flask = next(
            item for item in registry["implementations"] if item["id"] == "python-flask"
        )
        self.assertEqual(flask["display_name"], "Python / Flask")


if __name__ == "__main__":
    unittest.main()
