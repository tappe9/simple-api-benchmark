"""Docker exec-event contracts for the healthcheck interference investigation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import environment, healthcheck
from benchmark.results import BenchmarkFailure

CID = "a" * 64
EXEC_ID = "b" * 64
PROBE = ["/go-gin", "healthcheck"]


def event(action: str, *, exec_id: str = EXEC_ID, container_id: str = CID, at: int = 1):
    return {
        "Type": "container",
        "Action": action,
        "Actor": {
            "ID": container_id,
            "Attributes": {"execID": exec_id},
        },
        "timeNano": at,
    }


def encoded(*events: dict) -> bytes:
    return ("\n".join(json.dumps(value, separators=(",", ":")) for value in events) + "\n").encode()


class EventParserTests(unittest.TestCase):
    def test_matching_probe_lifecycle_is_counted_once_by_exec_id(self):
        summary = healthcheck.parse_exec_events(
            encoded(
                event("exec_create: /go-gin healthcheck", at=10),
                event("exec_start: /go-gin healthcheck", at=11),
                event("exec_die", at=12),
            ),
            container_id=CID,
            probe_command=PROBE,
        )
        self.assertEqual(summary["total_execs"], 1)
        self.assertEqual(summary["probe_execs"], 1)
        self.assertEqual(summary["non_probe_execs"], 0)
        self.assertEqual(summary["probe_start_timestamps_ns"], [11])
        healthcheck.require_probe_only_activity(summary)

    def test_non_probe_exec_is_classified_and_rejected_for_baseline(self):
        summary = healthcheck.parse_exec_events(
            encoded(
                event("exec_create: sh -c surprise", at=20),
                event("exec_start: sh -c surprise", at=21),
                event("exec_die", at=22),
            ),
            container_id=CID,
            probe_command=PROBE,
        )
        self.assertEqual(summary["non_probe_execs"], 1)
        with self.assertRaises(BenchmarkFailure):
            healthcheck.require_probe_only_activity(summary)

    def test_controlled_policy_rejects_any_exec_activity(self):
        empty = healthcheck.parse_exec_events(b"", container_id=CID, probe_command=None)
        healthcheck.require_no_exec_activity(empty)
        activity = healthcheck.parse_exec_events(
            encoded(
                event("exec_create: /go-gin healthcheck", at=30),
                event("exec_start: /go-gin healthcheck", at=31),
                event("exec_die", at=32),
            ),
            container_id=CID,
            probe_command=None,
        )
        with self.assertRaises(BenchmarkFailure):
            healthcheck.require_no_exec_activity(activity)

    def test_malformed_wrong_container_invalid_lifecycle_and_overflow_fail_closed(self):
        bad_inputs = (
            b"not-json\n",
            encoded(event("exec_start: /go-gin healthcheck", container_id="c" * 64)),
            encoded(event("exec_die")),
            encoded(
                event("exec_create: /go-gin healthcheck", at=2),
                event("exec_start: /different command", at=3),
            ),
            encoded(*[event("exec_create: /go-gin healthcheck", exec_id=f"{i:064x}") for i in range(129)]),
        )
        for raw in bad_inputs:
            with self.subTest(raw=raw[:40]), self.assertRaises(BenchmarkFailure):
                healthcheck.parse_exec_events(
                    raw,
                    container_id=CID,
                    probe_command=PROBE,
                    max_events=128,
                )


class EnvironmentAuditTests(unittest.TestCase):
    def _measure(self, *, audit: bool):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"),
                Path(directory),
                audit_health_events=audit,
            )
            env.container = CID
            env.implementation = "go-gin"
            env.probe_command = PROBE

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
            event_summary = {
                "total_execs": 1,
                "probe_execs": 1,
                "non_probe_execs": 0,
                "probe_start_timestamps_ns": [11],
            }
            with (
                patch.object(env, "check"),
                patch.object(environment, "execute", side_effect=execute),
                patch.object(env, "probe_events", return_value=event_summary) as probe_events,
                patch("benchmark.results.parse_oha", return_value=parsed),
            ):
                result = env.measure("/json", 1, 1)

            if audit:
                probe_events.assert_called_once()
            else:
                probe_events.assert_not_called()
            return result

    def test_measurement_attaches_events_only_when_investigation_audit_is_enabled(self):
        normal = self._measure(audit=False)
        investigated = self._measure(audit=True)
        self.assertNotIn("health_probe_events", normal)
        self.assertEqual(investigated["health_probe_events"]["probe_execs"], 1)

    def test_probe_event_query_is_interval_scoped_to_owned_container(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"), Path(directory), audit_health_events=True
            )
            env.container = CID
            env.probe_command = PROBE
            raw = encoded(
                event("exec_create: /go-gin healthcheck", at=10),
                event("exec_start: /go-gin healthcheck", at=11),
                event("exec_die", at=12),
            ).decode()
            with patch.object(environment, "execute", return_value=raw) as execute:
                summary = env.probe_events(
                    environment.datetime(2026, 9, 9, 2, 0, 0, tzinfo=environment.timezone.utc),
                    environment.datetime(2026, 9, 9, 2, 0, 30, tzinfo=environment.timezone.utc),
                )
            command = execute.call_args.args[0]
            self.assertEqual(command[:2], ["docker", "events"])
            self.assertIn("container=" + CID, command)
            for action in ("exec_create", "exec_start", "exec_die"):
                self.assertIn("event=" + action, command)
            self.assertIn("--since", command)
            self.assertIn("--until", command)
            self.assertEqual(summary["probe_execs"], 1)


if __name__ == "__main__":
    unittest.main()
