"""Regression tests for Node / Express container acceptance checks."""

import json
import subprocess
import unittest
from unittest.mock import patch

from test_node_express_service import DB_ENVIRONMENT, CheckFailure, check_configuration, check_running_service


class ConfigurationTests(unittest.TestCase):
    def configuration(self):
        return {"services": {"node-express": {
            "build": {"context": "apps/node-express"},
            "environment": {**DB_ENVIRONMENT, "NODE_ENV": "production"},
            "depends_on": {"postgres": {"condition": "service_healthy"}},
            "cpus": 1,
            "mem_limit": 536870912,
            "restart": "no",
            "networks": {"benchmark": None},
            "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8080}],
            "healthcheck": {"test": ["CMD", "node", "src/healthcheck.js"]},
        }}}

    def test_accepts_exact_shared_limits(self):
        check_configuration(self.configuration())

    def test_rejects_wrong_cpu_or_public_port(self):
        config = self.configuration()
        config["services"]["node-express"]["cpus"] = 2
        with self.assertRaisesRegex(CheckFailure, "resource limits"):
            check_configuration(config)
        config = self.configuration()
        config["services"]["node-express"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaisesRegex(CheckFailure, "loopback"):
            check_configuration(config)


class ProcessTests(unittest.TestCase):
    def test_rejects_multiple_server_processes(self):
        state = {"State":{"Health":{"Status":"healthy"}},"RestartCount":0,"HostConfig":{"NanoCpus":1000000000,"Memory":536870912,"Privileged":False,"CapDrop":["ALL"],"SecurityOpt":["no-new-privileges:true"]},"Config":{"User":"node"},"Path":"node","Args":["src/server.js"],"NetworkSettings":{"Ports":{"8080/tcp":[{"HostIp":"127.0.0.1","HostPort":"8080"}]}}}
        def fake(command, **_kwargs):
            if command[:4] == ["docker","compose","ps","--quiet"]: out = "container-id\n"
            elif command[:2] == ["docker","inspect"]: out = json.dumps([state])
            elif command[:2] == ["docker","top"]: out = "PID COMMAND\n1 node src/server.js\n2 node src/server.js\n"
            else: out = ""
            return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")
        with patch("test_node_express_service.run", side_effect=fake), self.assertRaisesRegex(CheckFailure, "one Node server"):
            check_running_service()


if __name__ == "__main__":
    unittest.main()
