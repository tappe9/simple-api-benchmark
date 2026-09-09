#!/usr/bin/env python3
"""Resolved Docker Compose parity checks for every registered API implementation."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from benchmark.registry import implementation_ids

ROOT = Path(__file__).resolve().parents[1]


class ComposeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        completed = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "docker compose config failed: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )
        cls.config = json.loads(completed.stdout)

    def test_every_registered_api_has_shared_isolation_policy(self) -> None:
        services = self.config["services"]
        for implementation in implementation_ids():
            with self.subTest(implementation=implementation):
                self.assertIn(implementation, services)
                service = services[implementation]
                self.assertEqual(
                    service["depends_on"]["postgres"]["condition"],
                    "service_healthy",
                )
                self.assertEqual(float(service["cpus"]), 1.0)
                self.assertEqual(str(service["mem_limit"]), "536870912")
                self.assertEqual(service["restart"], "no")
                self.assertEqual(set(service["networks"]), {"benchmark"})
                self.assertEqual(service.get("cap_drop"), ["ALL"])
                self.assertIn(
                    "no-new-privileges:true",
                    service.get("security_opt", []),
                )

                ports = service["ports"]
                self.assertEqual(len(ports), 1)
                self.assertEqual(ports[0]["host_ip"], "127.0.0.1")
                self.assertEqual(str(ports[0]["published"]), "8080")
                self.assertEqual(ports[0]["target"], 8080)

    def test_postgresql_does_not_publish_a_host_port(self) -> None:
        postgres = self.config["services"]["postgres"]
        self.assertFalse(postgres.get("ports"))


if __name__ == "__main__":
    unittest.main()
