"""Boundary cases for interval-scoped Docker health-probe event auditing."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from benchmark import environment, healthcheck

CID = "a" * 64
PROBE = ["/go-gin", "healthcheck"]


def event(action: str, *, exec_id: str, at: int) -> dict:
    return {
        "Type": "container",
        "Action": action,
        "Actor": {"ID": CID, "Attributes": {"execID": exec_id}},
        "timeNano": at,
    }


def encoded(*events: dict) -> bytes:
    return (
        "\n".join(json.dumps(value, separators=(",", ":")) for value in events) + "\n"
    ).encode()


def epoch_ns(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value.astimezone(timezone.utc) - epoch
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


class EventBoundaryTests(unittest.TestCase):
    def test_overlapping_probe_lifecycles_are_attributed_to_exact_measurement_window(self):
        before = "b" * 64
        left = "c" * 64
        inside = "d" * 64
        right = "e" * 64
        summary = healthcheck.parse_exec_events(
            encoded(
                event("exec_create: /go-gin healthcheck", exec_id=before, at=1),
                event("exec_start: /go-gin healthcheck", exec_id=before, at=2),
                event("exec_die", exec_id=before, at=3),
                event("exec_create: /go-gin healthcheck", exec_id=left, at=4),
                event("exec_start: /go-gin healthcheck", exec_id=left, at=5),
                event("exec_die", exec_id=left, at=11),
                event("exec_create: /go-gin healthcheck", exec_id=inside, at=12),
                event("exec_start: /go-gin healthcheck", exec_id=inside, at=13),
                event("exec_die", exec_id=inside, at=14),
                event("exec_create: /go-gin healthcheck", exec_id=right, at=18),
                event("exec_start: /go-gin healthcheck", exec_id=right, at=19),
            ),
            container_id=CID,
            probe_command=PROBE,
            window_started_ns=10,
            window_completed_ns=20,
        )
        self.assertEqual(summary["total_execs"], 3)
        self.assertEqual(summary["probe_execs"], 3)
        self.assertEqual(summary["non_probe_execs"], 0)
        self.assertEqual(summary["probe_start_timestamps_ns"], [5, 13, 19])

    def test_controlled_window_still_reports_an_exec_that_starts_before_right_boundary(self):
        right = "f" * 64
        summary = healthcheck.parse_exec_events(
            encoded(
                event("exec_create: sh -c surprise", exec_id=right, at=18),
                event("exec_start: sh -c surprise", exec_id=right, at=19),
            ),
            container_id=CID,
            probe_command=None,
            window_started_ns=10,
            window_completed_ns=20,
        )
        self.assertEqual(summary["total_execs"], 1)
        self.assertEqual(summary["non_probe_execs"], 1)

    def test_environment_looks_back_five_seconds_and_persists_raw_event_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(
                Path("/fake/oha"), Path(directory), audit_health_events=True
            )
            env.container = CID
            env.implementation = "go-gin"
            env.probe_command = PROBE
            started = datetime(2026, 9, 9, 3, 0, 10, tzinfo=timezone.utc)
            completed = datetime(2026, 9, 9, 3, 0, 20, tzinfo=timezone.utc)
            base = epoch_ns(started)
            raw = encoded(
                event("exec_create: /go-gin healthcheck", exec_id="1" * 64, at=base + 1),
                event("exec_start: /go-gin healthcheck", exec_id="1" * 64, at=base + 2),
                event("exec_die", exec_id="1" * 64, at=base + 3),
            ).decode()
            with patch.object(environment, "execute", return_value=raw) as execute:
                env.probe_events(started, completed)

            command = execute.call_args.args[0]
            self.assertEqual(command[command.index("--since") + 1], "2026-09-09T03:00:05Z")
            self.assertEqual(command[command.index("--until") + 1], "2026-09-09T03:00:20Z")
            logs = list(env.artifacts.glob("*-events-*.jsonl"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text(encoding="utf-8"), raw)


if __name__ == "__main__":
    unittest.main()
