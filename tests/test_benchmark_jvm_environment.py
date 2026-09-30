"""Diagnostic-only JVM window evidence, with bounded command doubles."""

import importlib
import importlib.util
import json
import math
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from benchmark import environment
from benchmark.healthcheck import EXTERNAL_READINESS
from benchmark.results import BenchmarkFailure

CID = "a" * 64
FIXTURE = Path(__file__).parent / "fixtures" / "oha-1.16.0" / "timed.json"


class DiagnosticEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("benchmark.jvm_environment"),
            "diagnostic-only environment module is required",
        )
        self.module = importlib.import_module("benchmark.jvm_environment")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = self.module.DiagnosticEnvironment(Path("/fake/oha"), Path(self.directory.name))
        self.env.container = CID
        self.env.implementation = "java-spring-boot"
        self.commands = []
        self.payload = FIXTURE.read_bytes()
        self.stats = json.dumps({"ID": CID, "CPUPerc": "73.25%", "MemUsage": "12MiB / 512MiB"})
        self.load_failure = None

    def execute(self, arguments, *, timeout, tick=None, **kwargs):
        self.commands.append((arguments, timeout))
        if arguments[:2] == ["docker", "stats"]:
            return self.stats
        if "--output" in arguments:
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(self.payload)
            tick()
            if self.load_failure:
                # Evidence must already be flushed before a command fails.
                self.assertTrue(list(self.env.artifacts.glob("*.stats.jsonl"))[0].read_text())
                raise self.load_failure
            return "oha stdout\n"
        if "logs" in arguments:
            return "owned container log\n"
        return ""

    def measure(self, index=4, endpoint="/json"):
        with (
            patch.object(self.env, "check"),
            patch.object(self.module, "execute", side_effect=self.execute),
        ):
            return self.env.measure(endpoint, 1, index)

    def window(self, index=4):
        return self.env.artifacts / f"java-spring-boot-json-window-{index}.window.json"

    def test_inherits_scoped_cleanup_and_external_readiness_without_tuning(self):
        self.assertIs(
            self.module.DiagnosticEnvironment.cleanup, environment.DockerEnvironment.cleanup
        )
        self.assertEqual(self.env.health_policy, EXTERNAL_READINESS)
        self.assertEqual((self.env.connections, self.env.request_timeout), (50, 15))
        self.assertFalse(self.env.audit_health_events)

    def test_validated_p95_cpu_and_raw_stats_are_preserved_for_window_four(self):
        result = self.measure()
        raw = json.loads(self.payload)
        self.assertEqual(result["p95_response_time_ms"], raw["latencyPercentiles"]["p95"] * 1000)
        self.assertEqual(result["run"], 4)
        self.assertEqual(result["window_index"], 4)
        self.assertEqual(result["peak_memory_bytes"], 12 * 1024**2)
        self.assertEqual(result["memory_samples"], 1)
        self.assertEqual(result["cpu_percent_samples"], [73.25])
        base = self.env.artifacts / "java-spring-boot-json-window-4"
        self.assertEqual(base.with_suffix(".json").read_bytes(), self.payload)
        sample = json.loads(base.with_suffix(".stats.jsonl").read_text())
        self.assertEqual(sample["raw"], self.stats)
        self.assertLessEqual(
            datetime.fromisoformat(sample["started_at"]),
            datetime.fromisoformat(sample["completed_at"]),
        )
        memory = json.loads(base.with_suffix(".memory.jsonl").read_text())
        self.assertEqual(memory["bytes"], 12 * 1024**2)
        self.assertEqual(memory["cpu_percent"], 73.25)

    def test_window_timing_and_status_are_persisted(self):
        result = self.measure(0)
        window = json.loads(self.window(0).read_text())
        self.assertEqual(window["status"], "complete")
        self.assertEqual(window["window_index"], 0)
        self.assertEqual(window["started_at"], result["started_at"])
        self.assertEqual(window["completed_at"], result["completed_at"])
        self.assertGreaterEqual(window["duration_wall_seconds"], 0)
        self.assertIsNotNone(datetime.fromisoformat(window["started_at"]).tzinfo)
        self.assertLessEqual(
            datetime.fromisoformat(window["started_at"]),
            datetime.fromisoformat(window["completed_at"]),
        )

    def test_oha_arguments_match_common_load_contract(self):
        self.measure()
        command, timeout = next(
            (args, timeout) for args, timeout in self.commands if "--output" in args
        )
        expected = [
            "/fake/oha",
            "--no-tui",
            "--output-format",
            "json",
            "--output",
            str(self.env.artifacts / "java-spring-boot-json-window-4.json"),
            "--http-version",
            "1.1",
            "--redirect",
            "0",
            "--disable-compression",
            "-c",
            "50",
            "-z",
            "1s",
            "-w",
            "-t",
            "15s",
            "--connect-timeout",
            "5s",
            "http://127.0.0.1:8080/json",
        ]
        self.assertEqual(command, expected)
        self.assertEqual(timeout, 31)
        self.assertEqual(
            len([args for args, _ in self.commands if args[:2] == ["docker", "stats"]]), 1
        )

    def test_failed_load_retains_partial_stats_raw_oha_logs_and_window_timing(self):
        self.load_failure = BenchmarkFailure("command exited 1: oha\npartial failure output")
        with self.assertRaisesRegex(BenchmarkFailure, "partial failure output"):
            self.measure()
        self.assertEqual(json.loads(self.window().read_text())["status"], "failed")
        self.assertIn(
            "partial failure output",
            (self.env.artifacts / "java-spring-boot-json-window-4.load.log").read_text(),
        )
        self.assertEqual(
            (self.env.artifacts / "java-spring-boot-json-window-4.json").read_bytes(), self.payload
        )
        self.assertTrue(list(self.env.artifacts.glob("*.stats.jsonl"))[0].read_text())
        self.assertIn(
            "owned container log",
            (self.env.artifacts / "java-spring-boot-json-window-4-container.log").read_text(),
        )
        logs, timeout = next((args, timeout) for args, timeout in self.commands if "logs" in args)
        self.assertIn(self.env.project, logs)
        self.assertIn("--tail", logs)
        self.assertLessEqual(timeout, 15)

    def test_invalid_cpu_retains_raw_sample_but_invalidates_window(self):
        for cpu in (None, "NaN%", "-1%", "inf%", "1", True):
            self.stats = json.dumps({"ID": CID, "CPUPerc": cpu, "MemUsage": "12MiB / 512MiB"})
            with self.subTest(cpu=cpu), self.assertRaises(BenchmarkFailure):
                self.measure()
            self.assertEqual(
                json.loads(list(self.env.artifacts.glob("*.stats.jsonl"))[0].read_text())["raw"],
                self.stats,
            )
            self.assertEqual(json.loads(self.window().read_text())["status"], "failed")

    def test_p95_missing_or_nonfinite_is_rejected_by_common_parser(self):
        for value in (None, math.inf, math.nan, "missing"):
            data = json.loads(FIXTURE.read_bytes())
            if value == "missing":
                del data["latencyPercentiles"]["p95"]
            else:
                data["latencyPercentiles"]["p95"] = value
            self.payload = json.dumps(data).encode()
            with self.subTest(value=value), self.assertRaises(BenchmarkFailure):
                self.measure()
            self.assertEqual(json.loads(self.window().read_text())["status"], "failed")

    def test_oha_error_response_is_retained_but_never_validated_as_success(self):
        self.payload = FIXTURE.with_name("http-error.json").read_bytes()
        with self.assertRaises(BenchmarkFailure):
            self.measure()
        self.assertEqual(
            (self.env.artifacts / "java-spring-boot-json-window-4.json").read_bytes(), self.payload
        )
        self.assertEqual(json.loads(self.window().read_text())["status"], "failed")

    def test_build_failure_preserves_existing_command_error_output(self):
        failure = BenchmarkFailure("command exited 1: docker compose build\ncompiler details")
        with (
            patch.object(environment, "execute", side_effect=failure),
            patch.object(self.module, "execute", side_effect=self.execute),
        ):
            with self.assertRaisesRegex(BenchmarkFailure, "compiler details"):
                self.env.build("java-spring-boot")
        self.assertIn(
            "compiler details", (self.env.artifacts / "java-spring-boot-build.log").read_text()
        )

    def test_start_context_is_allowlisted_and_has_no_environment_secrets(self):
        public = {
            "id": CID,
            "image_id": "sha256:123",
            "command": ["java", "-jar", "app.jar"],
            "postgresql_version": "PostgreSQL 18.6",
        }
        state = {
            "Id": CID,
            "Image": "sha256:123",
            "Config": {"Env": ["DATABASE_PASSWORD=secret-never-persist"]},
            "State": {"StartedAt": "2026-09-30T01:00:00Z"},
            "RestartCount": 0,
            "HostConfig": {"NanoCpus": 1000000000, "Memory": 536870912},
        }
        with (
            patch.object(environment.DockerEnvironment, "start", return_value=public),
            patch.object(self.env, "inspect", return_value=state),
        ):
            result = self.env.start("java-spring-boot")
        self.assertEqual(result["limits"], {"nano_cpus": 1000000000, "memory_bytes": 536870912})
        self.assertEqual(result["command"], public["command"])
        saved = (self.env.artifacts / "java-spring-boot-context.json").read_text()
        self.assertNotIn("secret-never-persist", saved)
        self.assertNotIn("DATABASE_PASSWORD", saved)
        self.assertEqual(json.loads(saved), result)

    def test_start_failure_captures_scoped_logs_without_masking_cause(self):
        failure = BenchmarkFailure("readiness failed")
        with (
            patch.object(environment.DockerEnvironment, "start", side_effect=failure),
            patch.object(self.module, "execute", side_effect=self.execute),
        ):
            with self.assertRaisesRegex(BenchmarkFailure, "readiness failed"):
                self.env.start("java-spring-boot")
        self.assertIn(
            "readiness failed",
            (self.env.artifacts / "java-spring-boot-start-failure.log").read_text(),
        )
        self.assertIn(
            "owned container log",
            (self.env.artifacts / "java-spring-boot-start-container.log").read_text(),
        )

    def test_evidence_write_failure_does_not_mask_failed_load(self):
        self.load_failure = BenchmarkFailure("original load failure")
        original = Path.write_text

        def fail_evidence(path, text, **kwargs):
            if path.suffix == ".log" or path.name.endswith(".window.json"):
                raise OSError("disk full")
            return original(path, text, **kwargs)

        with patch.object(Path, "write_text", fail_evidence):
            with self.assertRaisesRegex(BenchmarkFailure, "original load failure"):
                self.measure()

    def test_evidence_write_failure_does_not_mask_failed_build(self):
        failure = BenchmarkFailure("original build failure")
        with (
            patch.object(environment, "execute", side_effect=failure),
            patch.object(Path, "write_text", side_effect=OSError("disk full")),
        ):
            with self.assertRaisesRegex(BenchmarkFailure, "original build failure"):
                self.env.build("java-spring-boot")

    def test_constructor_rejects_measurement_policy_changes(self):
        for change in (
            {"connections": 1},
            {"request_timeout": 30},
            {"health_policy": "container-healthcheck"},
            {"audit_health_events": True},
        ):
            with self.subTest(change=change), self.assertRaises(BenchmarkFailure):
                self.module.DiagnosticEnvironment(
                    Path("/fake/oha"), Path(self.directory.name), **change
                )

    def test_all_approved_endpoints_have_safe_evidence_paths(self):
        for endpoint, label in (("/json", "json"), ("/db/42", "db-42"), ("/cpu", "cpu")):
            with self.subTest(endpoint=endpoint):
                self.measure(endpoint=endpoint)
                self.assertTrue(
                    (self.env.artifacts / f"java-spring-boot-{label}-window-4.json").is_file()
                )
                self.assertTrue(
                    (
                        self.env.artifacts / f"java-spring-boot-{label}-window-4.window.json"
                    ).is_file()
                )

    def test_invalid_window_indexes_do_not_start_load(self):
        for index in (-1, 5, True, 1.0):
            with self.subTest(index=index), self.assertRaises(BenchmarkFailure):
                self.measure(index)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
