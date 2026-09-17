"""Java registration must not activate a cohort or rewrite historical results."""

import unittest
from unittest.mock import patch

from benchmark import ci, environment, registry

EIGHT = ("go-gin", "go-echo", "rust-actix", "rust-axum", "node-fastify", "node-express", "python-fastapi", "python-flask")
BASELINE_VERSIONS = {'go-gin': {'go': '1.27.1', 'gin': '1.12.0', 'pgx': '5.10.0'}, 'go-echo': {'go': '1.27.1', 'echo': '5.3.1', 'pgx': '5.10.0'}, 'rust-actix': {'rust': '1.98.1', 'actix-web': '4.15.0', 'sqlx': '0.9.0', 'serde': '1.0.228', 'serde_json': '1.0.145'}, 'rust-axum': {'rust': '1.98.1', 'axum': '0.8.9', 'tokio': '1.53.1', 'sqlx': '0.9.0', 'serde': '1.0.228', 'serde_json': '1.0.145'}, 'node-fastify': {'node': '24.20.0', 'fastify': '5.12.3', 'pg': '8.23.0'}, 'node-express': {'node': '24.20.0', 'express': '5.2.1', 'pg': '8.23.0'}, 'python-fastapi': {'python': '3.14.7', 'fastapi': '0.141.1', 'uvicorn': '0.52.4', 'asyncpg': '0.31.0'}, 'python-flask': {'python': '3.14.7', 'flask': '3.1.3', 'waitress': '3.0.2', 'psycopg': '3.3.5', 'psycopg-binary': '3.3.5', 'psycopg-pool': '3.3.1'}}


class JavaCandidateTests(unittest.TestCase):
    def test_java_is_registered_but_official_members_are_unchanged(self):
        self.assertIn("java-spring-boot", registry.implementation_ids())
        self.assertEqual(tuple(registry.active_members()), EIGHT)
        self.assertEqual(registry.REGISTRY["active_cohort"], "eight-stack-v1")
        self.assertEqual(set(registry.REGISTRY["cohorts"]), {"four-stack-v1", "eight-stack-v1"})

    def test_metadata_is_read_without_running_any_language_toolchain(self):
        with patch("subprocess.run", side_effect=AssertionError("metadata must be static")):
            versions = environment.registered_pinned_versions()
        self.assertIn("java-spring-boot", versions)
        self.assertEqual(versions["java-spring-boot"]["java"], "25.0.4.1+1")
        self.assertEqual(versions["java-spring-boot"]["spring-boot"], "4.1.1")
        self.assertEqual(environment.pinned_versions(), BASELINE_VERSIONS)

    def test_java_has_its_own_ci_toolchain_without_changing_other_entries(self):
        entries = ci.matrix_payload()["include"]
        self.assertIn({"implementation": "java-spring-boot", "toolchain": "java"}, entries)
        self.assertEqual(len(entries), 9)


if __name__ == "__main__":
    unittest.main()
