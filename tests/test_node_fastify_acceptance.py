"""Regression tests for the Node / Fastify acceptance configuration checks."""

import unittest

from test_node_fastify_service import APP, DB_ENVIRONMENT, CheckFailure, check_configuration


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


if __name__ == "__main__":
    unittest.main()
