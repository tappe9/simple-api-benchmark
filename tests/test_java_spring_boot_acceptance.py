"""Regression tests for fail-closed Java production acceptance checks."""

import copy
import unittest

from test_java_spring_boot_service import (
    validate_failed_startup,
    validate_pool_count,
    validate_shutdown,
)


def exited(code=143):
    return {
        "State": {
            "Running": False,
            "Restarting": False,
            "Dead": False,
            "OOMKilled": False,
            "Status": "exited",
            "ExitCode": code,
        },
        "RestartCount": 0,
    }


class AcceptanceFailureTests(unittest.TestCase):
    def test_graceful_exit_accepts_only_normal_or_sigterm_exit(self):
        for code in (0, 143):
            validate_shutdown(exited(code), "0\n")
        for code in (1, 137, 139, True):
            with self.assertRaises(RuntimeError):
                validate_shutdown(exited(code), "0")

    def test_shutdown_rejects_oom_restart_running_or_live_database_sessions(self):
        for key in ("Running", "Restarting", "Dead", "OOMKilled"):
            value = exited()
            value["State"][key] = True
            with self.assertRaises(RuntimeError):
                validate_shutdown(value, "0")
        value = exited()
        value["RestartCount"] = 1
        with self.assertRaises(RuntimeError):
            validate_shutdown(value, "0")
        for count in ("1", "10", "", "bad", "-1"):
            with self.assertRaises(RuntimeError):
                validate_shutdown(exited(), count)

    def test_missing_inspect_fields_fail_instead_of_defaulting_to_success(self):
        for key in exited()["State"]:
            value = exited()
            del value["State"][key]
            with self.assertRaises(RuntimeError):
                validate_shutdown(value, "0")
        value = exited()
        del value["RestartCount"]
        with self.assertRaises(RuntimeError):
            validate_shutdown(value, "0")

    def test_pool_count_requires_one_bounded_integer(self):
        for value in ("0", "1\n", "10"):
            validate_pool_count(value)
        for value in ("11", "-1", "1.5", "true", "", "1\n2", "nan"):
            with self.assertRaises(RuntimeError):
                validate_pool_count(value)

    def test_startup_failure_must_be_an_actual_sanitized_application_failure(self):
        validate_failed_startup(exited(1), "application startup failed\n")
        for code in (0, 125, 126, 127, 137, 143):
            with self.assertRaises(RuntimeError):
                validate_failed_startup(exited(code), "application startup failed\n")
        for logs in (
            "docker command failed",
            "application startup failed\npassword=secret-67",
            "application startup failed\njdbc:postgresql://postgres",
            "application startup failed\nSELECT * FROM items",
            "application startup failed\nat org.example.Database.connect",
        ):
            with self.assertRaises(RuntimeError):
                validate_failed_startup(exited(1), logs)

    def test_startup_failure_rejects_oom_and_running_containers(self):
        baseline = exited(1)
        for key in ("Running", "Restarting", "Dead", "OOMKilled"):
            value = copy.deepcopy(baseline)
            value["State"][key] = True
            with self.assertRaises(RuntimeError):
                validate_failed_startup(value, "application startup failed")


if __name__ == "__main__":
    unittest.main()
