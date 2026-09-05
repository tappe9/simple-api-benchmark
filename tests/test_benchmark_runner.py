"""Stateful lifecycle doubles exercise ordering, cleanup and publication barriers."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_results import summary

from benchmark import run
from benchmark.contract_test import ContractFailure
from benchmark.results import BenchmarkFailure


class Environment:
    def __init__(self, fail=None):
        self.events = []
        self.active = None
        self.fixture = None
        self.fail = fail
        self.contract_seen = False
        self.measures = 0

    def event(self, name):
        self.events.append(name)
        if name == self.fail:
            raise BenchmarkFailure("injected " + name)

    def build(self, implementation):
        if self.active is not None:
            raise AssertionError("overlapping APIs")
        self.event("build")

    def start(self, implementation):
        self.active = implementation
        self.fixture = "fresh"
        self.contract_seen = False
        self.event("startup")
        return {"image_id": "sha256:test-only"}

    def check(self):
        self.event("state")

    def contract(self, base_url, *, implementation):
        self.event("contract")
        if self.fixture != "fresh" or self.active != implementation:
            raise AssertionError("fixture or service collision")
        self.fixture = "used by previous implementation"
        self.contract_seen = True
        return 14

    def measure(self, endpoint, duration, index):
        if not self.contract_seen:
            raise AssertionError("load before shared contract")
        self.event("warmup" if index == 0 else "measurement")
        self.events.append((self.active, endpoint, duration, index))
        self.measures += index > 0
        self.event("metric")
        return summary(max(index, 1), {1: 10500, 2: 9900, 3: 10100}.get(index, 100))

    def cleanup(self):
        self.active = None
        self.fixture = None
        self.event("cleanup")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "latest.json"
        self.output.write_bytes(b"previous verified result")
        self.config = run.load_config()
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def call(self, environment, **kwargs):
        return run.run_benchmark(
            environment,
            self.config,
            self.output,
            metadata={"source_commit": "fixture-only"},
            contract=environment.contract,
            **kwargs,
        )

    def test_sequential_fresh_fixtures_exact_fixed_runs_and_one_selected_run(self):
        environment = Environment()
        report = self.call(environment)
        self.assertIsNone(environment.active)
        self.assertEqual(environment.measures, 36)
        self.assertEqual(environment.events.count("cleanup"), 4)
        measured = [event for event in environment.events if type(event) is tuple]
        self.assertEqual(len(measured), 48)
        self.assertEqual(
            [event for event in measured if event[3] == 0],
            [
                (name, endpoint, 5, 0)
                for name in run.IMPLEMENTATIONS
                for endpoint in ("/json", "/db/42", "/cpu")
            ],
        )
        self.assertTrue(all(event[2] == 30 for event in measured if event[3] > 0))
        for backend in report["implementations"]:
            for result in backend["endpoints"]:
                self.assertEqual(result["selected"], summary(3, 10100))
                self.assertEqual(len(result["runs"]), 3)
        self.assertEqual(json.loads(self.output.read_bytes()), report)

    def test_all_failures_cleanup_protect_existing_result_and_stop(self):
        for failure in (
            "build",
            "startup",
            "contract",
            "state",
            "warmup",
            "measurement",
            "metric",
            "cleanup",
        ):
            environment = Environment(failure)
            with self.subTest(failure=failure), self.assertRaisesRegex(BenchmarkFailure, failure):
                self.call(environment)
            self.assertEqual(self.output.read_bytes(), b"previous verified result")
            self.assertIsNone(environment.active)
            self.assertEqual(environment.events[-1:], ["cleanup"])
            self.assertEqual(environment.events.count("build"), 1)
            if failure in ("build", "startup", "contract", "state"):
                self.assertEqual(environment.measures, 0)

    def test_actual_contract_exception_prevents_all_load(self):
        environment = Environment()
        with patch.object(environment, "contract", side_effect=ContractFailure("wrong JSON")):
            with self.assertRaisesRegex(BenchmarkFailure, "wrong JSON"):
                self.call(environment)
        self.assertEqual(environment.measures, 0)
        self.assertNotIn("warmup", environment.events)
        self.assertIsNone(environment.active)
        self.assertEqual(self.output.read_bytes(), b"previous verified result")

    def test_late_partial_failure_does_not_publish_or_retry(self):
        environment = Environment()
        original = environment.measure

        def fail_late(endpoint, duration, index):
            if environment.measures == 35:
                raise BenchmarkFailure("last run failed")
            return original(endpoint, duration, index)

        with patch.object(environment, "measure", side_effect=fail_late):
            with self.assertRaisesRegex(BenchmarkFailure, "last run failed"):
                self.call(environment)
        self.assertEqual(environment.measures, 35)
        self.assertIsNone(environment.active)
        self.assertEqual(self.output.read_bytes(), b"previous verified result")

    def test_invalid_metric_return_is_rejected(self):
        environment = Environment()
        bad = summary()
        bad["peak_memory_bytes"] = True
        with patch.object(environment, "measure", return_value=bad):
            with self.assertRaises(BenchmarkFailure):
                self.call(environment)
        self.assertEqual(self.output.read_bytes(), b"previous verified result")

    def test_interruption_and_timeout_cleanup(self):
        for failure in (KeyboardInterrupt("signal"), BenchmarkFailure("command timeout")):
            for stage in ("build", "start", "measure"):
                environment = Environment()
                with patch.object(environment, stage, side_effect=failure):
                    with self.assertRaises((KeyboardInterrupt, BenchmarkFailure)):
                        self.call(environment)
                self.assertIsNone(environment.active)
                self.assertEqual(environment.events[-1:], ["cleanup"])
                self.assertEqual(self.output.read_bytes(), b"previous verified result")

    def test_config_cannot_silently_change_baseline(self):
        for name in (
            "connections",
            "runs",
            "duration_seconds",
            "warmup_seconds",
            "workers",
            "pool_max",
            "api_cpus",
            "api_memory_bytes",
        ):
            for bad in (True, "1", 0, -1, 17):
                changed = copy.deepcopy(self.config)
                changed[name] = bad
                path = self.output.parent / "config.json"
                path.write_text(json.dumps(changed))
                with self.subTest(name=name, bad=bad), self.assertRaises(BenchmarkFailure):
                    run.load_config(path)

    def test_smoke_never_writes_requested_verified_destination(self):
        environment = Environment()
        report = self.call(environment, smoke=True)
        self.assertEqual(report["mode"], "smoke")
        self.assertEqual(self.output.read_bytes(), b"previous verified result")


class SignalTests(unittest.TestCase):
    def test_real_sigterm_uses_cli_handler_and_cleans_partial_startup(self):
        import os
        import signal
        import subprocess
        import sys
        import time

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "owned-resource"
            script = """
import sys, time
from pathlib import Path
from unittest.mock import patch
from benchmark import run, environment, install_oha
marker = Path(sys.argv[1])
class PartialStartup:
    def __init__(self, *args, **kwargs): self.artifacts = run.ROOT / ".cache/test-only"
    def build(self, implementation): pass
    def start(self, implementation):
        marker.write_text("owned")
        time.sleep(30)
    def cleanup(self): marker.unlink(missing_ok=True)
with patch.object(environment, 'DockerEnvironment', PartialStartup), patch.object(environment, 'provenance', return_value={}), patch.object(install_oha, 'ensure_oha', return_value=Path('/test-only/oha')):
    sys.exit(run.main([]))
"""
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(marker)],
                cwd=run.ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline and child.poll() is None:
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "partial startup was not reached")
                child.send_signal(signal.SIGTERM)
                output, _ = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 1, output)
                self.assertIn("received signal", output)
                self.assertFalse(marker.exists(), "CLI interruption leaked owned resources")
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)
