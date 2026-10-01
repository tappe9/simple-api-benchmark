"""Common screening evidence uses command doubles, never starts Docker or load."""

import copy
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
from benchmark.contract_test import ContractFailure, Response
from benchmark.results import BenchmarkFailure

CID = "a" * 64
PGID = "b" * 64
FIXTURE = Path(__file__).parent / "fixtures" / "oha-1.16.0" / "timed.json"


class CommonWarmupEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("benchmark.common_warmup_environment"),
            "separate common warmup screening environment is required",
        )
        self.module = importlib.import_module("benchmark.common_warmup_environment")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = self.module.CommonWarmupEnvironment(Path("/fake/oha"), Path(self.directory.name))
        self.api = self.state(CID, "go-gin")
        self.pg = self.state(PGID, "postgres")
        self.pg["State"]["Health"] = {"Status": "healthy", "Log": [{"Output": "secret"}]}
        self.pg["HostConfig"]["NanoCpus"] = 0
        self.pg["HostConfig"]["Memory"] = 0
        self.commands = []
        self.requests = []
        self.payload = FIXTURE.read_bytes()
        self.stats = json.dumps({"ID": CID, "CPUPerc": "73.25%", "MemUsage": "12MiB / 512MiB"})
        self.fixture_output = "42|Item 42|4200\n1\n"
        self.load_failure = None
        self.readiness_failure = None
        self.api_inspections = 0
        self.pg_inspections = 0
        self.change_after_load = None
        self.loaded = False
        self.process_list = "PID COMMAND\n42 /go-gin\n"
        self.process_requires_ready = False
        self.ready_observed = False

    def state(self, cid, service):
        value = {
            "Id": cid,
            "Image": "sha256:" + "c" * 64,
            "Path": "/go-gin" if service != "postgres" else "postgres",
            "Args": [],
            "RestartCount": 0,
            "State": {
                "Status": "running",
                "Running": True,
                "Restarting": False,
                "Dead": False,
                "OOMKilled": False,
                "StartedAt": "2026-01-01T00:00:00Z",
            },
            "HostConfig": {
                "NanoCpus": 1000000000,
                "Memory": 536870912,
                "RestartPolicy": {"Name": "no"},
            },
            "Config": {
                "Labels": {
                    "com.docker.compose.project": self.env.project,
                    "com.docker.compose.service": service,
                    "secret-label": "secret",
                },
                "Healthcheck": {"Test": ["NONE"]},
                "Env": ["DATABASE_PASSWORD=secret-never-persist"],
            },
        }
        if service == "postgres":
            value["HostConfig"]["Tmpfs"] = {"/var/lib/postgresql": "rw,size=512m,mode=1777"}
            value["Mounts"] = [
                {
                    "Type": "bind",
                    "Source": str(environment.ROOT / "database/init.sql"),
                    "Destination": "/docker-entrypoint-initdb.d/001-init.sql",
                    "RW": False,
                }
            ]
        return value

    def execute(self, args, *, timeout, tick=None, **kwargs):
        self.commands.append((args, timeout))
        if args[:2] == ["docker", "inspect"]:
            if args[2] == CID:
                self.api_inspections += 1
                value = copy.deepcopy(self.api)
                if self.loaded and self.change_after_load:
                    value["State"].update(self.change_after_load)
                return json.dumps([value])
            if args[2] == PGID:
                self.pg_inspections += 1
                return json.dumps([self.pg])
            raise AssertionError("unexpected inspect target")
        if "ps" in args and "--quiet" in args:
            return PGID if args[-1] == "postgres" else CID
        if "psql" in args:
            return (
                "PostgreSQL 18.6 on test\n" if "SELECT version();" in args else self.fixture_output
            )
        if args[:2] == ["docker", "top"]:
            if self.process_requires_ready and not self.ready_observed:
                return "PID COMMAND\n42 startup-wrapper\n"
            return self.process_list
        if args[:2] == ["docker", "stats"]:
            return self.stats
        if "--output" in args:
            Path(args[args.index("--output") + 1]).write_bytes(self.payload)
            tick()
            self.loaded = True
            if self.load_failure:
                raise self.load_failure
            return "oha stdout\n"
        if "logs" in args:
            return "owned log\n"
        return ""

    def reader(self, base_url, path, *, timeout):
        self.requests.append((base_url, path, timeout))
        if self.readiness_failure:
            raise self.readiness_failure
        self.ready_observed = True
        return Response(200, "application/json", b'{"status":"ok"}')

    def start(self):
        with (
            patch.object(self.module, "execute", side_effect=self.execute),
            patch.object(self.module, "read_response", side_effect=self.reader),
        ):
            return self.env.start("go-gin")

    def measure(self, index=8, endpoint="/json"):
        with patch.object(self.module, "execute", side_effect=self.execute):
            return self.env.measure(endpoint, 1, index)

    def evidence(self, name):
        return self.env.artifacts / ("go-gin-" + name)

    def test_cleanup_and_runtime_policy_remain_inherited_without_tuning(self):
        self.assertIs(
            self.module.CommonWarmupEnvironment.cleanup, environment.DockerEnvironment.cleanup
        )
        self.assertEqual((self.env.connections, self.env.request_timeout), (50, 15))
        self.assertEqual(self.env.health_policy, "external-readiness")
        self.assertFalse(self.env.audit_health_events)
        for kwargs in (
            {"connections": 1},
            {"request_timeout": 30},
            {"health_policy": "container-healthcheck"},
            {"audit_health_events": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(BenchmarkFailure):
                self.module.CommonWarmupEnvironment(
                    Path("/fake/oha"), Path(self.directory.name), **kwargs
                )

    def test_start_proves_postgres_fixture_before_starting_api_and_only_reads_health(self):
        context = self.start()
        commands = [args for args, _ in self.commands]
        fixture = next(
            i for i, args in enumerate(commands) if "psql" in args and "items" in args[-1]
        )
        api_start = next(
            i for i, args in enumerate(commands) if "up" in args and args[-1] == "go-gin"
        )
        self.assertLess(fixture, api_start)
        self.assertEqual([path for _, path, _ in self.requests], ["/health"])
        self.assertEqual(context["postgres"]["id"], PGID)
        self.assertEqual(
            context["postgres"]["fixture"],
            {"id": 42, "name": "Item 42", "price": 4200, "row_count": 1},
        )
        self.assertEqual(context["id"], CID)
        self.assertEqual(context["readiness"]["attempts"], 1)
        self.assertGreaterEqual(context["readiness"]["duration_seconds"], 0)
        self.assertEqual(context["limits"], {"nano_cpus": 1000000000, "memory_bytes": 536870912})
        self.assertEqual(self.evidence("postgres-fixture.log").read_text(), self.fixture_output)
        self.assertEqual(json.loads(self.evidence("context.json").read_text()), context)
        readiness = json.loads(self.evidence("readiness.jsonl").read_text())
        self.assertEqual(readiness["path"], "/health")
        self.assertEqual(readiness["response"]["body"], '{"status":"ok"}')

    def test_raw_state_evidence_is_allowlisted_and_keeps_timing_and_identities(self):
        self.start()
        self.measure()
        saved = self.evidence("state.jsonl").read_text()
        for forbidden in (
            "secret-never-persist",
            "DATABASE_PASSWORD",
            '"Env"',
            "secret-label",
            '"Log"',
        ):
            self.assertNotIn(forbidden, saved)
        records = [json.loads(line) for line in saved.splitlines()]
        self.assertEqual({r["role"] for r in records}, {"api", "postgres"})
        self.assertEqual({r["raw"]["Id"] for r in records}, {CID, PGID})
        self.assertTrue(all("StartedAt" in r["raw"]["State"] for r in records))
        self.assertTrue(
            all(
                datetime.fromisoformat(r["started_at"]) <= datetime.fromisoformat(r["completed_at"])
                for r in records
            )
        )

    def test_zero_and_eight_use_identical_common_load_arguments_and_raw_cpu_memory(self):
        self.start()
        for index in (0, 8):
            result = self.measure(index)
            self.assertEqual(result["window_index"], index)
            self.assertEqual(result["cpu_percent_samples"], [73.25])
            self.assertEqual(result["peak_memory_bytes"], 12 * 1024**2)
            self.assertEqual(
                result["p95_response_time_ms"],
                json.loads(self.payload)["latencyPercentiles"]["p95"] * 1000,
            )
            command, timeout = [call for call in self.commands if "--output" in call[0]][-1]
            self.assertEqual(
                command,
                [
                    "/fake/oha",
                    "--no-tui",
                    "--output-format",
                    "json",
                    "--output",
                    str(self.evidence(f"json-window-{index}.json")),
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
                ],
            )
            self.assertEqual(timeout, 31)
            raw = json.loads(self.evidence(f"json-window-{index}.stats.jsonl").read_text())
            self.assertEqual(raw["raw"], self.stats)
            self.assertEqual(self.evidence(f"json-window-{index}.json").read_bytes(), self.payload)
        self.assertEqual(len(self.requests), 1)

    def test_process_age_readiness_gap_and_between_window_gap_are_explicit(self):
        context = self.start()
        first = self.measure(0)
        second = self.measure(1)
        self.assertIsNone(first["gap_since_previous_window_seconds"])
        self.assertGreaterEqual(first["readiness_to_window_seconds"], 0)
        expected_gap = (
            datetime.fromisoformat(second["started_at"])
            - datetime.fromisoformat(first["completed_at"])
        ).total_seconds()
        self.assertAlmostEqual(second["gap_since_previous_window_seconds"], expected_gap)
        expected_age = (
            datetime.fromisoformat(first["started_at"])
            - datetime.fromisoformat(context["container_started_at"])
        ).total_seconds()
        self.assertAlmostEqual(first["process_age_seconds_at_start"], expected_age)
        self.assertGreaterEqual(
            first["process_age_seconds_at_completion"], first["process_age_seconds_at_start"]
        )
        saved = json.loads(self.evidence("json-window-0.window.json").read_text())
        for field in (
            "process_age_seconds_at_start",
            "process_age_seconds_at_completion",
            "gap_since_previous_window_seconds",
            "readiness_to_window_seconds",
        ):
            self.assertEqual(saved[field], first[field])

    def test_invalid_indexes_duration_or_endpoint_start_no_commands(self):
        for index in (-1, 9, True, 1.0):
            with self.subTest(index=index), self.assertRaises(BenchmarkFailure):
                self.measure(index)
        for duration in (0, -1, True, 1.0):
            with self.subTest(duration=duration), self.assertRaises(BenchmarkFailure):
                self.env.measure("/json", duration, 0)
        with self.assertRaises(BenchmarkFailure):
            self.measure(endpoint="/../../escape")
        self.assertEqual(self.commands, [])

    def test_bad_fixture_preserves_raw_output_and_never_starts_api(self):
        self.fixture_output = "42|Wrong|4200\n2\n"
        with self.assertRaisesRegex(BenchmarkFailure, "fixture"):
            self.start()
        self.assertEqual(self.evidence("postgres-fixture.log").read_text(), self.fixture_output)
        self.assertFalse(any("up" in args and args[-1] == "go-gin" for args, _ in self.commands))
        self.assertIn("fixture", self.evidence("start-failure.log").read_text())

    def test_postgres_requires_tmpfs_and_rejects_persistent_data_mount(self):
        self.pg["Mounts"].append(
            {"Type": "volume", "Destination": "/var/lib/postgresql/18/docker", "RW": True}
        )
        with self.assertRaisesRegex(BenchmarkFailure, "persistent"):
            self.start()
        self.assertFalse(any("up" in args and args[-1] == "go-gin" for args, _ in self.commands))

    def test_postgres_requires_readonly_fixture_mount(self):
        self.pg["Mounts"][0]["RW"] = True
        with self.assertRaisesRegex(BenchmarkFailure, "fixture mount"):
            self.start()
        records = [
            json.loads(line) for line in self.evidence("state.jsonl").read_text().splitlines()
        ]
        self.assertEqual(records[0]["raw"]["Mounts"][0]["RW"], True)

    def test_postgres_identity_health_restart_or_project_mismatch_fails_closed(self):
        for field, value in (("RestartCount", 1), ("Id", "c" * 64)):
            with self.subTest(field=field):
                old = self.pg[field]
                self.pg[field] = value
                with self.assertRaises(BenchmarkFailure):
                    self.start()
                self.pg[field] = old
                # Every failed attempt owns a fresh environment.
                self.env = self.module.CommonWarmupEnvironment(
                    Path("/fake/oha"), Path(self.directory.name)
                )
                self.api = self.state(CID, "go-gin")
                self.pg = self.state(PGID, "postgres")
                self.pg["State"]["Health"] = {"Status": "healthy"}
        self.pg["State"]["Health"] = {"Status": "unhealthy"}
        with self.assertRaises(BenchmarkFailure):
            self.start()
        self.assertTrue(self.evidence("state.jsonl").is_file())

    def test_api_resource_failure_retains_sanitized_state_before_validation(self):
        self.api["HostConfig"]["Memory"] = 0
        with self.assertRaisesRegex(BenchmarkFailure, "512 MiB"):
            self.start()
        records = [
            json.loads(line) for line in self.evidence("state.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            [r for r in records if r["role"] == "api"][-1]["raw"]["HostConfig"]["Memory"], 0
        )
        self.assertEqual(self.requests, [])

    def test_initial_api_inspect_must_match_requested_container_id(self):
        self.api["Id"] = "d" * 64
        with self.assertRaisesRegex(BenchmarkFailure, "API container identity"):
            self.start()
        self.assertEqual(self.requests, [])

    def test_enabled_healthcheck_rejected(self):
        self.api["Config"]["Healthcheck"]["Test"] = ["CMD", "/go-gin", "healthcheck"]
        with self.assertRaisesRegex(BenchmarkFailure, "healthcheck"):
            self.start()
        self.assertEqual(self.requests, [])

    def test_extra_api_process_rejected_and_process_evidence_retained(self):
        self.process_list += "43 unexpected-worker\n"
        with self.assertRaisesRegex(BenchmarkFailure, "server process"):
            self.start()
        self.assertEqual(self.evidence("processes.log").read_text(), self.process_list)

    def test_process_check_waits_for_readiness_so_worker_startup_can_finish(self):
        self.process_requires_ready = True
        self.start()
        self.assertTrue(self.ready_observed)
        self.assertEqual(self.evidence("processes.log").read_text(), self.process_list)

    def test_readiness_failure_is_logged_with_no_full_contract_calls(self):
        self.readiness_failure = ContractFailure("bad response framing")
        with self.assertRaisesRegex(ContractFailure, "bad response framing"):
            self.start()
        record = json.loads(self.evidence("readiness.jsonl").read_text())
        self.assertEqual(record["path"], "/health")
        self.assertIn("bad response framing", record["error"])
        self.assertEqual([p for _, p, _ in self.requests], ["/health"])
        self.assertIn("owned log", self.evidence("start-container.log").read_text())

    def test_failed_load_retains_stats_oha_timing_and_scoped_logs(self):
        self.start()
        self.load_failure = BenchmarkFailure("original partial failure")
        with self.assertRaisesRegex(BenchmarkFailure, "original partial failure"):
            self.measure()
        window = json.loads(self.evidence("json-window-8.window.json").read_text())
        self.assertEqual(window["status"], "failed")
        self.assertGreaterEqual(window["process_age_seconds_at_start"], 0)
        self.assertEqual(self.evidence("json-window-8.json").read_bytes(), self.payload)
        self.assertEqual(
            json.loads(self.evidence("json-window-8.stats.jsonl").read_text())["raw"], self.stats
        )
        self.assertIn(
            "original partial failure", self.evidence("json-window-8.load.log").read_text()
        )
        self.assertIn("owned log", self.evidence("json-window-8-container.log").read_text())
        for args, timeout in self.commands:
            if "logs" in args:
                self.assertIn(self.env.project, args)
                self.assertLessEqual(timeout, 15)

    def test_invalid_raw_cpu_and_oha_results_are_retained(self):
        self.start()
        self.stats = json.dumps({"ID": CID, "CPUPerc": "NaN%", "MemUsage": "12MiB / 512MiB"})
        with self.assertRaises(BenchmarkFailure):
            self.measure(0)
        self.assertEqual(
            json.loads(self.evidence("json-window-0.stats.jsonl").read_text())["raw"], self.stats
        )
        self.stats = json.dumps({"ID": CID, "CPUPerc": "1%", "MemUsage": "12MiB / 512MiB"})
        value = json.loads(self.payload)
        value["latencyPercentiles"]["p95"] = math.inf
        self.payload = json.dumps(value).encode()
        with self.assertRaises(BenchmarkFailure):
            self.measure(1)
        self.assertEqual(self.evidence("json-window-1.json").read_bytes(), self.payload)

    def test_restart_after_load_invalidates_retained_window(self):
        self.start()
        self.change_after_load = {"StartedAt": "2026-01-02T00:00:00Z"}
        with self.assertRaisesRegex(BenchmarkFailure, "identity"):
            self.measure()
        self.assertEqual(
            json.loads(self.evidence("json-window-8.window.json").read_text())["status"], "failed"
        )

    def test_postgres_checked_at_boundaries_but_never_inside_stats_sampling(self):
        self.start()
        before_pg = self.pg_inspections
        self.measure()
        self.assertEqual(self.pg_inspections - before_pg, 2)
        self.assertGreater(self.api_inspections, self.pg_inspections)

    def test_postgres_restart_between_windows_fails_before_another_load(self):
        self.start()
        self.measure(0)
        self.pg["RestartCount"] = 1
        with self.assertRaisesRegex(BenchmarkFailure, "PostgreSQL restart"):
            self.measure(1)
        self.assertEqual(len([args for args, _ in self.commands if "--output" in args]), 1)
        self.assertEqual(
            json.loads(self.evidence("json-window-1.window.json").read_text())["status"], "failed"
        )

    def test_invalid_process_age_does_not_mask_original_state_failure(self):
        self.start()
        self.env.identity = (CID, "2999-01-01T00:00:00Z")
        with self.assertRaisesRegex(BenchmarkFailure, "identity/start time changed"):
            self.measure()
        window = json.loads(self.evidence("json-window-8.window.json").read_text())
        self.assertEqual(window["status"], "failed")
        self.assertIn("container start time", window["timing_error"])

    def test_evidence_disk_failure_does_not_mask_failed_load(self):
        self.start()
        self.load_failure = BenchmarkFailure("original load failure")
        original = Path.write_text

        def fail_write(path, text, **kwargs):
            if path.suffix == ".log" or path.name.endswith(".window.json"):
                raise OSError("disk full")
            return original(path, text, **kwargs)

        with patch.object(Path, "write_text", fail_write):
            with self.assertRaisesRegex(BenchmarkFailure, "original load failure"):
                self.measure()

    def test_failed_build_retains_error_and_original_cause_when_logs_fail(self):
        with patch.object(self.module, "execute", side_effect=BenchmarkFailure("compiler details")):
            with self.assertRaisesRegex(BenchmarkFailure, "compiler details"):
                self.env.build("go-gin")
        self.assertIn("compiler details", self.evidence("build.log").read_text())
        self.assertIn("logs unavailable", self.evidence("build-container.log").read_text())

    def test_readiness_retries_are_individually_logged(self):
        from benchmark.healthcheck import wait_external_readiness

        times = iter(i / 100 for i in range(100))

        def wait(*args, **kwargs):
            return wait_external_readiness(
                *args, **kwargs, clock=lambda: next(times), sleep=lambda _: None
            )

        responses = [
            ContractFailure("transport: connection refused"),
            Response(200, "application/json", b'{"status":"ok"}'),
        ]
        with (
            patch.object(self.module, "execute", side_effect=self.execute),
            patch.object(self.module, "read_response", side_effect=responses),
            patch.object(self.module, "wait_external_readiness", side_effect=wait),
        ):
            context = self.env.start("go-gin")
        records = [
            json.loads(line) for line in self.evidence("readiness.jsonl").read_text().splitlines()
        ]
        self.assertEqual(context["readiness"]["attempts"], 2)
        self.assertEqual(len(records), 2)
        self.assertIn("connection refused", records[0]["error"])
        self.assertEqual(records[1]["response"]["status"], 200)

    def test_window_evidence_cannot_be_overwritten_and_start_requires_fresh_instance(self):
        self.start()
        self.measure()
        original = self.evidence("json-window-8.window.json").read_bytes()
        count = len(self.commands)
        with self.assertRaisesRegex(BenchmarkFailure, "already"):
            self.measure()
        self.assertEqual(self.evidence("json-window-8.window.json").read_bytes(), original)
        self.assertEqual(len(self.commands), count)
        with self.assertRaisesRegex(BenchmarkFailure, "fresh"):
            self.start()


if __name__ == "__main__":
    unittest.main()
