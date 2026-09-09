"""Health-policy contracts for the non-publishing interference investigation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import environment, healthcheck
from benchmark.contract_test import ContractFailure, Response
from benchmark.results import BenchmarkFailure


def process_state():
    return {
        "Path": "/go-gin",
        "Args": ["serve"],
        "Config": {"Healthcheck": {"Test": ["CMD", "/go-gin", "healthcheck"]}},
    }


def container_state(project: str, health_test=None):
    if health_test is None:
        health_test = ["NONE"]
    return {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Path": "/go-gin",
        "Args": ["serve"],
        "RestartCount": 0,
        "State": {
            "Status": "running",
            "Running": True,
            "Restarting": False,
            "Dead": False,
            "OOMKilled": False,
            "StartedAt": "2026-09-09T01:00:00Z",
        },
        "HostConfig": {
            "NanoCpus": 1000000000,
            "Memory": 536870912,
            "RestartPolicy": {"Name": "no"},
        },
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": "go-gin",
            },
            "Healthcheck": {"Test": health_test},
        },
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


class ExternalReadinessTests(unittest.TestCase):
    def test_transport_failure_retries_until_exact_health_response(self):
        now = [100.0]
        sleeps = []
        checks = []
        responses = iter(
            [
                ContractFailure("transport: connection refused"),
                Response(200, "application/json; charset=utf-8", b'{"status":"ok"}'),
            ]
        )

        def clock():
            return now[0]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        def reader(base_url, path, *, timeout):
            self.assertEqual((base_url, path), ("http://127.0.0.1:8080", "/health"))
            self.assertLessEqual(timeout, 2.0)
            value = next(responses)
            if isinstance(value, BaseException):
                raise value
            return value

        result = healthcheck.wait_external_readiness(
            "http://127.0.0.1:8080",
            "go-gin",
            lambda: checks.append(True),
            timeout_seconds=60.0,
            request_timeout=2.0,
            clock=clock,
            sleep=sleep,
            reader=reader,
        )
        self.assertEqual(result, {"attempts": 2, "duration_seconds": 0.25})
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(checks), 3)

    def test_wrong_health_response_fails_without_retrying(self):
        for response in (
            Response(503, "application/json", b'{"status":"ok"}'),
            Response(200, "text/plain", b'{"status":"ok"}'),
            Response(200, "application/json", b'{"status":"bad"}'),
        ):
            with self.subTest(response=response):
                sleeps = []
                with self.assertRaises(ContractFailure):
                    healthcheck.wait_external_readiness(
                        "http://127.0.0.1:8080",
                        "go-gin",
                        lambda: None,
                        timeout_seconds=1.0,
                        clock=lambda: 0.0,
                        sleep=sleeps.append,
                        reader=lambda *_args, **_kwargs: response,
                    )
                self.assertEqual(sleeps, [])

    def test_transport_failure_is_bounded_by_absolute_deadline(self):
        now = [0.0]

        def clock():
            return now[0]

        def sleep(seconds):
            now[0] += seconds

        def refused(*_args, **_kwargs):
            raise ContractFailure("transport: refused")

        with self.assertRaisesRegex(BenchmarkFailure, "readiness deadline"):
            healthcheck.wait_external_readiness(
                "http://127.0.0.1:8080",
                "go-gin",
                lambda: None,
                timeout_seconds=0.5,
                request_timeout=0.2,
                clock=clock,
                sleep=sleep,
                reader=refused,
            )
        self.assertLessEqual(now[0], 0.5)

    def test_controlled_start_waits_for_postgres_but_not_api_health(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"),
                Path(directory),
                health_policy=healthcheck.EXTERNAL_READINESS,
            )
            env.implementation = "go-gin"
            value = container_state(env.project)
            commands = []

            def execute(arguments, **_kwargs):
                commands.append(arguments)
                if "ps" in arguments and "--quiet" in arguments:
                    return value["Id"]
                if arguments[:2] == ["docker", "top"]:
                    return "PID COMMAND\n123 /go-gin serve\n"
                if "SELECT version();" in arguments:
                    return "PostgreSQL 18.6 (Debian 18.6-1.pgdg13+1)"
                return ""

            with (
                patch.object(environment, "execute", side_effect=execute),
                patch.object(env, "inspect", return_value=value),
                patch.object(
                    environment,
                    "wait_external_readiness",
                    return_value={"attempts": 2, "duration_seconds": 0.25},
                ) as readiness,
            ):
                info = env.start("go-gin")

            up_commands = [command for command in commands if "up" in command]
            self.assertEqual(len(up_commands), 2)
            postgres, api = up_commands
            self.assertEqual(postgres[-1], "postgres")
            self.assertIn("--wait", postgres)
            self.assertEqual(api[-1], "go-gin")
            self.assertNotIn("--wait", api)
            self.assertTrue(any("external-readiness.compose.yml" in part for part in api))
            readiness.assert_called_once()
            self.assertEqual(env.readiness, {"attempts": 2, "duration_seconds": 0.25})
            self.assertEqual(info["id"], value["Id"])

    def test_audited_baseline_records_probe_readiness_evidence_without_changing_start_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"),
                Path(directory),
                audit_health_events=True,
            )
            value = container_state(
                env.project,
                ["CMD", "/go-gin", "healthcheck"],
            )
            value["State"]["Health"] = {"Status": "healthy"}
            commands = []

            def execute(arguments, **_kwargs):
                commands.append(arguments)
                if "ps" in arguments and "--quiet" in arguments:
                    return value["Id"]
                if arguments[:2] == ["docker", "top"]:
                    return "PID COMMAND\n123 /go-gin serve\n"
                if "SELECT version();" in arguments:
                    return "PostgreSQL 18.6 (Debian 18.6-1.pgdg13+1)"
                return ""

            readiness_events = {
                "total_execs": 3,
                "probe_execs": 3,
                "non_probe_execs": 0,
                "probe_start_timestamps_ns": [1, 2, 3],
            }
            with (
                patch.object(environment, "execute", side_effect=execute),
                patch.object(env, "inspect", return_value=value),
                patch.object(env, "probe_events", return_value=readiness_events) as probe_events,
            ):
                info = env.start("go-gin")

            up_commands = [command for command in commands if "up" in command]
            self.assertEqual(len(up_commands), 1)
            self.assertIn("--wait", up_commands[0])
            self.assertEqual(up_commands[0][-1], "go-gin")
            probe_events.assert_called_once()
            self.assertEqual(env.readiness["attempts"], 3)
            self.assertGreaterEqual(env.readiness["duration_seconds"], 0.0)
            self.assertEqual(info["id"], value["Id"])


if __name__ == "__main__":
    unittest.main()
