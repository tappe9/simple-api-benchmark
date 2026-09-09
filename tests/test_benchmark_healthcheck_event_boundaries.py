"""Boundary cases for interval-scoped Docker health-probe event auditing."""

import json
import unittest

from benchmark import healthcheck

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


if __name__ == "__main__":
    unittest.main()
