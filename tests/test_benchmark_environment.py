"""Docker payload validation and installer integrity tests using explicit doubles."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import environment, install_oha
from benchmark.results import BenchmarkFailure


def state():
    return {
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "RestartCount": 0,
        "State": {
            "Status": "running",
            "Running": True,
            "Restarting": False,
            "Dead": False,
            "OOMKilled": False,
            "StartedAt": "2026-09-05T11:00:00Z",
        },
        "HostConfig": {
            "NanoCpus": 1000000000,
            "Memory": 536870912,
            "RestartPolicy": {"Name": "no"},
        },
        "Config": {
            "Labels": {
                "com.docker.compose.project": "owned",
                "com.docker.compose.service": "go-gin",
            }
        },
    }


class StateTests(unittest.TestCase):
    def test_exact_state_and_identity_are_validated(self):
        value = state()
        identity = environment.validate_state(value, "owned", "go-gin")
        self.assertEqual(identity, (value["Id"], value["State"]["StartedAt"]))
        environment.validate_state(value, "owned", "go-gin", identity)

    def test_exit_restart_stop_start_oom_and_resource_changes_rejected(self):
        original = state()
        identity = environment.validate_state(original, "owned", "go-gin")
        changes = (
            ("RestartCount", 1),
            ("RestartCount", False),
            ("State.Running", False),
            ("State.Running", 1),
            ("State.Restarting", True),
            ("State.Dead", True),
            ("State.OOMKilled", True),
            ("State.Status", "exited"),
            ("State.StartedAt", "2026-09-05T11:01:00Z"),
            ("HostConfig.NanoCpus", 2000000000),
            ("HostConfig.Memory", 0),
            ("HostConfig.RestartPolicy.Name", "always"),
            ("Id", "c" * 64),
        )
        for path, replacement in changes:
            value = copy.deepcopy(original)
            keys = path.split(".")
            target = value
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(BenchmarkFailure):
                environment.validate_state(value, "owned", "go-gin", identity)

    def test_wrong_project_missing_state_or_wrong_service_rejected(self):
        for value, project, service in (
            ({}, "owned", "go-gin"),
            (state(), "manual", "go-gin"),
            (state(), "owned", "postgres"),
        ):
            with self.assertRaises(BenchmarkFailure):
                environment.validate_state(value, project, service)

    def test_memory_units_and_api_identity(self):
        cid = "a" * 64
        for text, expected in (
            ("1.5MiB / 512MiB", 1572864),
            ("100KiB / 512MiB", 102400),
            ("1024B / 512MiB", 1024),
        ):
            self.assertEqual(
                environment.memory_bytes(json.dumps({"ID": cid, "MemUsage": text}), cid), expected
            )
        for text in (
            "",
            "0B / 0B",
            "NaNMiB / 512MiB",
            "1MB / 512MiB",
            "-1MiB / 512MiB",
            "513MiB / 512MiB",
            "True",
            "1MiB / 256MiB",
        ):
            with self.subTest(text=text), self.assertRaises(BenchmarkFailure):
                environment.memory_bytes(json.dumps({"ID": cid, "MemUsage": text}), cid)
        with self.assertRaises(BenchmarkFailure):
            environment.memory_bytes(
                json.dumps({"ID": "postgres-id", "MemUsage": "1MiB / 512MiB"}), cid
            )

    def test_owned_prefix_overrides_ambient_project_and_tears_down_only_it(self):
        with tempfile.TemporaryDirectory() as directory:
            env = environment.DockerEnvironment(Path("/fake/oha"), Path(directory))
            with patch.object(environment, "execute", return_value="") as commands:
                env.cleanup()
            arguments = [call.args[0] for call in commands.call_args_list]
            self.assertIn("-p", arguments[0])
            self.assertIn(env.project, arguments[0])
            self.assertTrue(env.project.startswith("sab-benchmark-"))
            for command in arguments[1:]:
                self.assertIn("label=com.docker.compose.project=" + env.project, command)


class InstallerTests(unittest.TestCase):
    def test_cached_checksum_is_checked_before_executing_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            binary = cache / "oha-linux-amd64"
            binary.write_bytes(b"untrusted")
            with (
                patch.object(install_oha, "platform_asset", return_value="oha-linux-amd64"),
                patch.object(install_oha, "execute") as execute,
            ):
                with self.assertRaisesRegex(BenchmarkFailure, "checksum"):
                    install_oha.ensure_oha(cache)
                execute.assert_not_called()

    def test_download_verifies_hash_and_version_before_atomic_install(self):
        with tempfile.TemporaryDirectory() as directory:
            content = b"test binary, not a real executable"
            digest = hashlib.sha256(content).hexdigest()

            def execute(arguments, **kwargs):
                if arguments[0] == "curl":
                    Path(arguments[-1]).write_bytes(content)
                    return ""
                self.assertEqual(arguments[1:], ["--version"])
                self.assertEqual(Path(arguments[0]).read_bytes(), content)
                return "oha 1.16.0\n"

            with (
                patch.object(install_oha, "platform_asset", return_value="oha-linux-amd64"),
                patch.dict(install_oha.SHA256, {"oha-linux-amd64": digest}),
                patch.object(install_oha, "execute", side_effect=execute),
            ):
                path = install_oha.ensure_oha(Path(directory))
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_wrong_version_and_download_failure_leave_no_installed_file(self):
        for failure in ("version", "download"):
            with tempfile.TemporaryDirectory() as directory:
                content = b"wrong version"

                def execute(arguments, **kwargs):
                    if arguments[0] == "curl":
                        Path(arguments[-1]).write_bytes(content)
                        if failure == "download":
                            raise BenchmarkFailure("download timeout")
                        return ""
                    return "oha 0.0.0"

                with (
                    patch.object(install_oha, "platform_asset", return_value="oha-linux-amd64"),
                    patch.dict(
                        install_oha.SHA256, {"oha-linux-amd64": hashlib.sha256(content).hexdigest()}
                    ),
                    patch.object(install_oha, "execute", side_effect=execute),
                ):
                    with self.assertRaises(BenchmarkFailure):
                        install_oha.ensure_oha(Path(directory))
                self.assertEqual(list(Path(directory).iterdir()), [])


class ProcessContractTests(unittest.TestCase):
    def test_common_server_check_accepts_one_server_and_independent_probe(self):
        value = {
            "Path": "python",
            "Args": ["-m", "uvicorn", "app:app", "--workers", "1"],
            "Config": {"Healthcheck": {"Test": ["CMD", "python", "-m", "health"]}},
        }
        environment.validate_processes(
            value,
            "PID COMMAND\n123 /opt/venv/bin/python -m uvicorn app:app --workers 1\n124 python -m health\n",
        )
        for text in (
            "PID COMMAND\n",
            "PID COMMAND\n123 python -m uvicorn app:app --workers 1\n124 python -m uvicorn app:app --workers 1\n",
            "PID COMMAND\n123 python -m uvicorn app:app --workers 1\n125 python child.py\n",
        ):
            with self.subTest(text=text), self.assertRaises(BenchmarkFailure):
                environment.validate_processes(value, text)

    def test_context_flags_cannot_redirect_compose_to_another_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            for compose in ("", "docker --context remote compose", "podman compose"):
                with self.assertRaises(BenchmarkFailure):
                    environment.DockerEnvironment(
                        Path("/fake/oha"), Path(directory), compose=compose
                    )
