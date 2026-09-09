"""Health-policy contracts for the non-publishing interference investigation."""

import tempfile
import unittest
from pathlib import Path

from benchmark import environment, healthcheck
from benchmark.results import BenchmarkFailure


def process_state():
    return {
        "Path": "/go-gin",
        "Args": ["serve"],
        "Config": {"Healthcheck": {"Test": ["CMD", "/go-gin", "healthcheck"]}},
    }


class PolicyTests(unittest.TestCase):
    def test_default_policy_is_current_container_healthcheck(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(Path("/fake/oha"), Path(directory))
        self.assertEqual(env.health_policy, healthcheck.CONTAINER_HEALTHCHECK)

    def test_policy_parser_accepts_only_named_policies(self):
        for value in (healthcheck.CONTAINER_HEALTHCHECK, healthcheck.EXTERNAL_READINESS):
            self.assertEqual(healthcheck.validate_policy(value), value)
        for value in ("", "disabled", "external", None, True):
            with self.subTest(value=value), self.assertRaises(BenchmarkFailure):
                healthcheck.validate_policy(value)

    def test_external_override_disables_only_registered_api_health(self):
        text = healthcheck.override_text("go-gin")
        self.assertEqual(
            text,
            "services:\n  go-gin:\n    healthcheck:\n      disable: true\n",
        )
        self.assertNotIn("postgres:", text)
        with self.assertRaises(BenchmarkFailure):
            healthcheck.override_text("unknown-api")

    def test_controlled_process_contract_requires_exactly_one_server(self):
        value = process_state()
        one = "PID COMMAND\n123 /go-gin serve\n"
        environment.validate_processes(value, one, allow_health_probe=False)
        with self.assertRaises(BenchmarkFailure):
            environment.validate_processes(
                value,
                one + "124 /go-gin healthcheck\n",
                allow_health_probe=False,
            )

    def test_baseline_process_contract_still_allows_only_configured_probe(self):
        value = process_state()
        environment.validate_processes(
            value,
            "PID COMMAND\n123 /go-gin serve\n124 /go-gin healthcheck\n",
        )
        with self.assertRaises(BenchmarkFailure):
            environment.validate_processes(
                value,
                "PID COMMAND\n123 /go-gin serve\n125 sh -c surprise\n",
            )


if __name__ == "__main__":
    unittest.main()
