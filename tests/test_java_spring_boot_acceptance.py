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

class DistributionPinTests(unittest.TestCase):
    @staticmethod
    def valid_manifest():
        lines = []
        for platform, architecture, pins in (("amd64", "x64", "ab"), ("arm64", "aarch64", "cd")):
            lines.append(f"FROM scratch AS archives-{platform}")
            for kind, pin in zip(("jdk", "jre"), pins):
                lines.append(
                    f"ADD --checksum=sha256:{pin * 64} "
                    "https://github.com/adoptium/temurin25-binaries/releases/download/"
                    f"jdk-25.0.4.1%2B1/OpenJDK25U-{kind}_{architecture}_linux_hotspot_"
                    f"25.0.4.1_1.tar.gz /tmp/{kind}.tar.gz"
                )
        lines.append("FROM archives-${TARGETARCH} AS archives")
        return "\n".join(lines) + "\n"

    def test_both_platforms_have_exactly_two_sha256_pins(self):
        from test_java_spring_boot_service import validate_distribution_pins
        validate_distribution_pins(self.valid_manifest())

    def test_bad_length_non_hex_and_missing_platform_are_rejected(self):
        from test_java_spring_boot_service import validate_distribution_pins
        valid = self.valid_manifest()
        for old in ("a", "b", "c", "d"):
            for bad in (old * 63, old * 65, "g" * 64, ""):
                with self.subTest(pin=old, value=bad):
                    with self.assertRaises(RuntimeError):
                        validate_distribution_pins(valid.replace(old * 64, bad))
        for bad in (
            valid.replace("FROM scratch AS archives-arm64", "FROM scratch AS missing"),
            valid + valid,
            valid.replace("_aarch64_", "_x64_"),
            valid.replace("${TARGETARCH}", "amd64"),
            valid.replace("github.com/adoptium/", "example.com/adoptium/"),
            valid.replace("/tmp/jre.tar.gz", "/tmp/jdk.tar.gz"),
        ):
            with self.assertRaises(RuntimeError):
                validate_distribution_pins(bad)

    def test_repository_distribution_manifest_is_well_formed(self):
        from test_java_spring_boot_service import APP, validate_distribution_pins
        validate_distribution_pins((APP / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
