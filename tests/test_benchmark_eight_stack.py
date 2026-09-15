"""Real eight-stack cohort compatibility; fixtures are never measurements."""

import unittest

from benchmark.registry import load_registry

LEGACY_MEMBERS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")
EIGHT_MEMBERS = (
    "go-gin",
    "go-echo",
    "rust-actix",
    "rust-axum",
    "node-fastify",
    "node-express",
    "python-fastapi",
    "python-flask",
)


class EightStackRegistryTests(unittest.TestCase):
    def test_real_eight_stack_cohort_is_registered_in_frozen_order(self):
        registry = load_registry()
        self.assertIn("eight-stack-v1", registry["cohorts"])
        self.assertEqual(
            registry["cohorts"]["eight-stack-v1"],
            {"definition": "simple-api-v1", "members": list(EIGHT_MEMBERS)},
        )

    def test_legacy_membership_and_order_are_unchanged(self):
        self.assertEqual(
            load_registry()["cohorts"]["four-stack-v1"],
            {"definition": "simple-api-v1", "members": list(LEGACY_MEMBERS)},
        )


if __name__ == "__main__":
    unittest.main()
