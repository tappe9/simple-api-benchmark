"""Runtime enforcement for the approved external-readiness benchmark policy."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_healthcheck import container_state

from benchmark import environment, healthcheck
from benchmark.results import BenchmarkFailure

CID = "a" * 64


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

    def test_warmup_and_measured_runs_never_call_readiness_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"),
                Path(directory),
                health_policy=healthcheck.EXTERNAL_READINESS,
            )
            env.container = CID
            env.implementation = "go-gin"

            def execute(arguments, *, timeout, tick=None, cwd=environment.ROOT):
                if arguments[:2] == ["docker", "stats"]:
                    return json.dumps({"ID": CID, "MemUsage": "1MiB / 512MiB"})
                if "--output" in arguments:
                    output = Path(arguments[arguments.index("--output") + 1])
                    output.write_bytes(b"{}")
                    if tick is not None:
                        tick()
                return ""

            parsed = {
                "requests_per_second": 1.0,
                "mean_response_time_ms": 1.0,
                "elapsed_seconds": 1.0,
                "successful_requests": 1,
                "response_bytes": 1,
            }
            with (
                patch.object(env, "check"),
                patch.object(environment, "execute", side_effect=execute),
                patch.object(
                    environment,
                    "wait_external_readiness",
                    side_effect=AssertionError("readiness polling entered load window"),
                ) as readiness,
                patch("benchmark.results.parse_oha", return_value=parsed),
            ):
                env.measure("/json", 1, 0)
                env.measure("/json", 1, 1)

            readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
