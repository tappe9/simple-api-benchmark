"""Regression checks for the Python service acceptance assertions themselves."""

import copy
import unittest

from test_python_fastapi_service import (
    APP,
    DB_ENVIRONMENT,
    SERVER_ARGS,
    CheckFailure,
    check_configuration,
    check_server_processes,
)


def configuration(memory=536870912):
    return {"services": {"python-fastapi": {
        "build": {"context": str(APP)}, "environment": dict(DB_ENVIRONMENT),
        "depends_on": {"postgres": {"condition": "service_healthy"}},
        "cpus": 1.0, "mem_limit": memory, "restart": "no", "networks": {"benchmark": None},
        "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8080}],
        "healthcheck": {"test": ["CMD", "python", "-m", "benchmark_api.healthcheck"]},
    }}}


class AcceptanceTests(unittest.TestCase):
    def test_integer_and_string_byte_limits(self):
        for memory in (536870912, "536870912"):
            with self.subTest(memory=memory):
                check_configuration(configuration(memory))

    def test_invalid_memory_limits_fail(self):
        for memory in (None, 536870912.0, 536870911, "512m"):
            with self.subTest(memory=memory), self.assertRaises(CheckFailure):
                check_configuration(configuration(memory))

    def test_wrong_cpu_fails(self):
        config = configuration()
        config["services"]["python-fastapi"]["cpus"] = 2
        with self.assertRaises(CheckFailure):
            check_configuration(config)

    def test_exposed_port_fails(self):
        config = configuration()
        config["services"]["python-fastapi"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(CheckFailure):
            check_configuration(config)

    def test_missing_readiness_and_restart_policy_fail(self):
        for key, value in (("restart", "always"), ("depends_on", {"postgres": {"condition": "service_started"}})):
            with self.subTest(key=key), self.assertRaises(CheckFailure):
                config = copy.deepcopy(configuration())
                config["services"]["python-fastapi"][key] = value
                check_configuration(config)

    def test_one_server_with_an_independent_health_probe(self):
        check_server_processes(["python " + " ".join(SERVER_ARGS), "python -m benchmark_api.healthcheck"])

    def test_zero_or_multiple_workers_fail(self):
        server = "python " + " ".join(SERVER_ARGS)
        for commands in ([], [server, server], [server, "python -c multiprocessing.spawn"], ["sh -c " + server]):
            with self.subTest(commands=commands), self.assertRaises(CheckFailure):
                check_server_processes(commands)


if __name__ == "__main__":
    unittest.main()
