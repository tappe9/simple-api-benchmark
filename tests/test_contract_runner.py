"""Lifecycle tests use a subprocess Compose double; Docker acceptance runs separately."""

import contextlib
import io
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import contract_runner as runner
from benchmark.contract_test import ContractFailure

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATIONS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")
COMPOSE_DOUBLE = """import json, os, pathlib, sys, time
args = sys.argv[1:]
project = args[args.index("-p") + 1]
operation = args[args.index("-p") + 2]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"project": project, "operation": operation, "args": args}) + "\\n")
state = pathlib.Path(os.environ["FAKE_STATE"])
if operation == "up":
    if state.exists():
        sys.exit("port conflict: previous service was not cleaned up")
    state.write_text("fresh fixture")
if os.environ.get("FAKE_FAIL") == operation:
    sys.exit("injected " + operation + " failure")
if os.environ.get("FAKE_STALL") == operation:
    time.sleep(30)
if operation == "down":
    state.unlink(missing_ok=True)
"""


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name)
        script = path / "compose double.py"
        script.write_text(COMPOSE_DOUBLE)
        self.compose = shlex.join([sys.executable, str(script)])
        self.log = path / "commands.jsonl"
        self.state = path / "container-and-network"
        environment = {
            "FAKE_LOG": str(self.log),
            "FAKE_STATE": str(self.state),
            "FAKE_FAIL": "",
            "FAKE_STALL": "",
            "COMPOSE_PROJECT_NAME": "manual-project",
        }
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_all_implementations_are_sequential_with_fresh_fixtures_and_same_suite(self):
        seen = []

        def contract(base_url, *, implementation):
            self.assertEqual(base_url, "http://127.0.0.1:8080")
            self.assertEqual(self.state.read_text(), "fresh fixture")
            self.state.write_text("changed by this implementation")
            seen.append(implementation)
            return 14

        with patch.object(runner, "run_contract", side_effect=contract):
            self.assertEqual(runner.run_implementations(IMPLEMENTATIONS, compose=self.compose), 56)
        self.assertEqual(seen, list(IMPLEMENTATIONS))
        self.assertFalse(self.state.exists())
        commands = self.commands()
        self.assertEqual([c["operation"] for c in commands], ["build", "up", "down"] * 4)
        self.assertEqual(len({c["project"] for c in commands}), 1)
        self.assertTrue(commands[0]["project"].startswith("sab-contract-"))
        self.assertNotEqual(commands[0]["project"], "manual-project")
        for command in commands:
            self.assertEqual(command["args"][1], str(ROOT / "docker-compose.yml"))
            if command["operation"] == "down":
                self.assertIn("--volumes", command["args"])
                self.assertIn("--remove-orphans", command["args"])
            if command["operation"] == "up":
                self.assertIn("--wait", command["args"])
                self.assertIn("--wait-timeout", command["args"])

    def test_one_implementation_uses_the_identical_suite(self):
        with patch.object(runner, "run_contract", return_value=14) as suite:
            self.assertEqual(
                runner.run_implementations(("python-fastapi",), compose=self.compose), 14
            )
        suite.assert_called_once_with("http://127.0.0.1:8080", implementation="python-fastapi")
        self.assertFalse(self.state.exists())

    def test_contract_failure_cleans_and_prevents_the_next_implementation(self):
        with patch.object(runner, "run_contract", side_effect=ContractFailure("wrong JSON")):
            with self.assertRaisesRegex(ContractFailure, "wrong JSON"):
                runner.run_implementations(IMPLEMENTATIONS, compose=self.compose)
        self.assertFalse(self.state.exists())
        self.assertEqual([c["operation"] for c in self.commands()], ["build", "up", "down"])

    def test_build_and_partial_startup_failure_clean_without_running_the_suite(self):
        for operation in ("build", "up"):
            self.log.unlink(missing_ok=True)
            with (
                self.subTest(operation=operation),
                patch.dict(os.environ, {"FAKE_FAIL": operation}),
                patch.object(runner, "run_contract") as suite,
            ):
                with self.assertRaisesRegex(ContractFailure, f"injected {operation} failure"):
                    runner.run_implementations(IMPLEMENTATIONS, compose=self.compose)
                suite.assert_not_called()
                self.assertFalse(self.state.exists())
                self.assertEqual(self.commands()[-1]["operation"], "down")

    def test_cleanup_failure_is_not_reported_as_success(self):
        with (
            patch.dict(os.environ, {"FAKE_FAIL": "down"}),
            patch.object(runner, "run_contract", return_value=14),
        ):
            with self.assertRaisesRegex(ContractFailure, "injected down failure"):
                runner.run_implementations(IMPLEMENTATIONS, compose=self.compose)
        self.assertEqual(len(self.commands()), 3)

    def test_cleanup_error_does_not_hide_the_original_contract_failure(self):
        with (
            patch.dict(os.environ, {"FAKE_FAIL": "down"}),
            patch.object(runner, "run_contract", side_effect=ContractFailure("original mismatch")),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            with self.assertRaisesRegex(ContractFailure, "original mismatch"):
                runner.run_implementations(IMPLEMENTATIONS, compose=self.compose)
        self.assertIn("cleanup", errors.getvalue())
        self.assertIn("injected down failure", errors.getvalue())

    def test_invalid_selection_or_empty_compose_is_rejected_before_any_commands(self):
        for implementations, compose in (
            (("not-a-service",), self.compose),
            ((), self.compose),
            (("go-gin",), ""),
        ):
            with self.subTest(implementations=implementations), self.assertRaises(ContractFailure):
                runner.run_implementations(implementations, compose=compose)
        self.assertFalse(self.log.exists())

    def test_separate_invocations_use_separate_projects(self):
        with patch.object(runner, "run_contract", return_value=14):
            runner.run_implementations(("go-gin",), compose=self.compose)
            runner.run_implementations(("go-gin",), compose=self.compose)
        self.assertNotEqual(self.commands()[0]["project"], self.commands()[3]["project"])

    def test_sigterm_during_startup_stops_the_command_and_cleans(self):
        with patch.dict(os.environ, {"FAKE_STALL": "up"}):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "benchmark.contract_runner",
                    "--implementation",
                    "go-gin",
                    "--compose",
                    self.compose,
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while (
                    not self.state.exists()
                    and process.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertTrue(self.state.exists(), "runner never started the service")
                process.send_signal(signal.SIGTERM)
                _, errors = process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("signal", errors)
                self.assertFalse(self.state.exists())
                self.assertEqual(self.commands()[-1]["operation"], "down")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


class CommandTests(unittest.TestCase):
    def test_nonzero_exit_and_missing_executable_fail(self):
        for command in (
            [sys.executable, "-c", 'raise SystemExit("bad startup")'],
            ["/no/such/compose"],
        ):
            with self.subTest(command=command), self.assertRaises(ContractFailure):
                runner.command(command, timeout=1)

    def test_timeout_kills_descendant_processes_before_cleanup_can_start(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "late-container"
            child = f"import time,pathlib; time.sleep(0.5); pathlib.Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
            with self.assertRaisesRegex(ContractFailure, "timeout"):
                runner.command([sys.executable, "-c", parent], timeout=0.15)
            time.sleep(0.6)
            self.assertFalse(marker.exists(), "an orphan command created a container after cleanup")


if __name__ == "__main__":
    unittest.main()
