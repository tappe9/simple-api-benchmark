"""Regression tests for the Node / Fastify acceptance checks."""

import json
import subprocess
import unittest
from unittest.mock import patch

from test_node_fastify_service import (
    APP, DB_ENVIRONMENT, DEPENDENCIES, CheckFailure, check_configuration, check_running_service,
)


class ConfigurationTests(unittest.TestCase):
    def configuration(self, memory):
        return {"services": {"node-fastify": {
            "build": {"context": str(APP)},
            "environment": {**DB_ENVIRONMENT, "NODE_ENV": "production"},
            "depends_on": {"postgres": {"condition": "service_healthy"}},
            "cpus": 1,
            "mem_limit": memory,
            "restart": "no",
            "networks": {"benchmark": None},
            "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8080}],
            "healthcheck": {"test": ["CMD", "node", "src/healthcheck.js"]},
        }}}

    def test_accepts_exact_memory_limit_as_integer_or_decimal_string(self):
        for memory in (536870912, "536870912"):
            with self.subTest(memory=memory):
                check_configuration(self.configuration(memory))

    def test_rejects_incorrect_memory_limits(self):
        for memory in (0, 536870911, 536870913, "536870911", "536870913", "512m", 536870912.5):
            with self.subTest(memory=memory), self.assertRaisesRegex(CheckFailure, "resource limits"):
                check_configuration(self.configuration(memory))

    def test_still_rejects_incorrect_cpu_limit(self):
        config = self.configuration("536870912")
        config["services"]["node-fastify"]["cpus"] = 2
        with self.assertRaisesRegex(CheckFailure, "resource limits"):
            check_configuration(config)

    def test_still_rejects_non_loopback_publication(self):
        config = self.configuration(536870912)
        config["services"]["node-fastify"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaisesRegex(CheckFailure, "loopback-only"):
            check_configuration(config)


class ProcessTests(unittest.TestCase):
    def check_processes(self, processes):
        state = {
            "State": {"Health": {"Status": "healthy"}},
            "RestartCount": 0,
            "HostConfig": {
                "NanoCpus": 1000000000, "Memory": 536870912,
                "Privileged": False, "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
            },
            "Config": {"User": "node"},
            "Path": "node", "Args": ["src/server.js"],
            "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}},
        }

        def fake_run(command):
            if command == ["docker", "compose", "ps", "--quiet", "node-fastify"]:
                output = "container-id\n"
            elif command == ["docker", "inspect", "container-id"]:
                output = json.dumps([state])
            elif command[:2] == ["docker", "top"]:
                self.assertEqual(command, ["docker", "top", "container-id", "-eo", "pid,args"])
                output = "PID COMMAND\n" + processes
            elif command[:3] == ["docker", "compose", "exec"]:
                output = json.dumps({"dependencies": {
                    name: {"version": version} for name, version in DEPENDENCIES.items()
                }}) if "npm" in command else ""
            else:
                self.fail(f"unexpected command: {command}")
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        with patch("test_node_fastify_service.run", side_effect=fake_run):
            return check_running_service()

    def test_requests_pid_column_and_accepts_one_server(self):
        self.assertEqual(self.check_processes("  123 node src/server.js\n"), "container-id")

    def test_rejects_multiple_servers(self):
        with self.assertRaisesRegex(CheckFailure, "not one Node server"):
            self.check_processes("123 node src/server.js\n124 node src/server.js\n")

    def test_rejects_missing_server(self):
        with self.assertRaisesRegex(CheckFailure, "not one Node server"):
            self.check_processes("123 node src/healthcheck.js\n")


if __name__ == "__main__":
    unittest.main()
