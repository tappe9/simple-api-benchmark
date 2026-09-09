"""Runtime enforcement for the approved external-readiness benchmark policy."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_healthcheck import container_state

from benchmark import environment, healthcheck
from benchmark.results import BenchmarkFailure


class RuntimePolicyTests(unittest.TestCase):
    def test_external_start_rejects_api_container_if_healthcheck_is_still_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"),
                Path(directory),
                health_policy=healthcheck.EXTERNAL_READINESS,
            )
            state = container_state(
                env.project,
                ["CMD", "/go-gin", "healthcheck"],
            )

            def execute(arguments, **_kwargs):
                if "ps" in arguments and "--quiet" in arguments:
                    return state["Id"]
                if arguments[:2] == ["docker", "top"]:
                    return "PID COMMAND\n123 /go-gin serve\n"
                if "SELECT version();" in arguments:
                    return "PostgreSQL 18.6 (Debian 18.6-1.pgdg13+1)"
                return ""

            with (
                patch.object(environment, "execute", side_effect=execute),
                patch.object(env, "inspect", return_value=state),
                patch.object(
                    environment,
                    "wait_external_readiness",
                    return_value={"attempts": 1, "duration_seconds": 0.1},
                ),
            ):
                with self.assertRaisesRegex(BenchmarkFailure, "healthcheck.*disabled"):
                    env.start("go-gin")


if __name__ == "__main__":
    unittest.main()
