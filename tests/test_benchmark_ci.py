"""Registry-derived CI setup and real subprocess dependency-isolation contracts."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from benchmark import ci, registry

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    {"implementation": "go-gin", "toolchain": "go"},
    {"implementation": "go-echo", "toolchain": "go"},
    {"implementation": "rust-actix", "toolchain": "rust"},
    {"implementation": "rust-axum", "toolchain": "rust"},
    {"implementation": "node-fastify", "toolchain": "node"},
    {"implementation": "node-express", "toolchain": "node"},
    {"implementation": "python-fastapi", "toolchain": "python"},
    {"implementation": "python-flask", "toolchain": "python"},
    {"implementation": "java-spring-boot", "toolchain": "java"},
]
COMMANDS = {
    "go": ("go", "gofmt"),
    "rust": (
        "rustup",
        "rustc",
        "rustdoc",
        "cargo",
        "rustfmt",
        "cargo-fmt",
        "cargo-clippy",
        "clippy-driver",
    ),
    "node": ("node", "nodejs", "npm", "npx", "corepack"),
    "python": (),
    "java": ("java", "javac", "jar", "javadoc", "gradle"),
}


class CIPlanningTests(unittest.TestCase):
    def test_matrix_selects_exactly_one_toolchain_for_every_registered_implementation(self):
        self.assertEqual(ci.matrix_payload(), {"include": EXPECTED})

    def test_matrix_includes_registered_members_outside_active_cohort_in_registry_order(self):
        data = copy.deepcopy(registry.REGISTRY)
        data["active_cohort"] = "four-stack-v1"
        data["implementations"].reverse()
        with patch.object(registry, "REGISTRY", data):
            self.assertEqual(ci.matrix_payload(), {"include": list(reversed(EXPECTED))})

    def test_new_supported_implementation_uses_language_not_identifier_prefix(self):
        data = copy.deepcopy(registry.REGISTRY)
        extra = copy.deepcopy(data["implementations"][0])
        extra.update(id="custom-example", source_path="apps/custom-example")
        data["implementations"].append(extra)
        with patch.object(registry, "REGISTRY", data):
            self.assertEqual(
                ci.matrix_payload(),
                {"include": EXPECTED + [{"implementation": "custom-example", "toolchain": "go"}]},
            )

    def test_unknown_language_and_invalid_registry_fail_before_emitting_matrix(self):
        for value in ("Synthetic go", "go", "Node", "", None, []):
            data = copy.deepcopy(registry.REGISTRY)
            data["implementations"][0]["language"] = value
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(language=value), patch.object(registry, "REGISTRY", data):
                with redirect_stdout(output), redirect_stderr(errors):
                    status = ci.main(["matrix"])
                self.assertEqual(status, 1)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("CI validation failed:", errors.getvalue())

    def test_duplicate_or_empty_registry_cannot_create_partial_matrix(self):
        for entries in ([], registry.REGISTRY["implementations"] * 2):
            data = copy.deepcopy(registry.REGISTRY)
            data["implementations"] = entries
            with patch.object(registry, "REGISTRY", data), self.assertRaises(RuntimeError):
                ci.matrix_payload()

    def test_matrix_cli_emits_one_compact_github_output_record(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmark.ci", "matrix"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.count("\n"), 1)
        key, payload = result.stdout.rstrip("\n").split("=", 1)
        self.assertEqual(key, "matrix")
        self.assertEqual(json.loads(payload), {"include": EXPECTED})

    def test_aggregate_rejects_each_missing_result(self):
        valid = dict.fromkeys(("plan", "shared", "implementation", "smoke"), "success")
        for key in valid:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                ci.require_success({name: value for name, value in valid.items() if name != key})


class ToolchainIsolationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            callable(getattr(ci, "run_isolated", None)), "isolated CI runner is missing"
        )
        self.temporary = tempfile.TemporaryDirectory(prefix="sab-test-ci-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.common = ("python", "python3", "make", "docker", "git", "sh")
        for command in (*self.common, *(name for group in COMMANDS.values() for name in group)):
            path = self.bin / command
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o700)

    def test_required_toolchain_and_common_harness_remain_available_for_all_registered(self):
        for entry in EXPECTED:
            commands = [*self.common, *COMMANDS[entry["toolchain"]]]
            script = (
                "import subprocess; " + f"[subprocess.run([c], check=True) for c in {commands!r}]"
            )
            with self.subTest(implementation=entry["implementation"]):
                with patch.dict(os.environ, {"PATH": str(self.bin)}):
                    self.assertEqual(
                        ci.run_isolated(entry["implementation"], [sys.executable, "-c", script]), 0
                    )

    def test_undeclared_preinstalled_tools_fail_even_when_child_ignores_exit_status(self):
        for entry in EXPECTED:
            blocked = [
                command
                for group, commands in COMMANDS.items()
                if group != entry["toolchain"]
                for command in commands
            ]
            evidence = self.directory / "blocked.json"
            script = (
                "import json, subprocess; from pathlib import Path; "
                f"results = [(c, subprocess.run([c], capture_output=True).returncode) for c in {blocked!r}]; "
                f"Path({str(evidence)!r}).write_text(json.dumps(results))"
            )
            with self.subTest(implementation=entry["implementation"]):
                with patch.dict(os.environ, {"PATH": str(self.bin)}):
                    with self.assertRaisesRegex(RuntimeError, "undeclared host toolchain"):
                        ci.run_isolated(entry["implementation"], [sys.executable, "-c", script])
                self.assertEqual(
                    json.loads(evidence.read_text()), [[name, 127] for name in blocked]
                )

    def test_optional_rust_version_probe_reports_absent_without_using_host_compiler(self):
        # pip's User-Agent probe catches this failure; wheel installs do not need Rust.
        for entry in EXPECTED:
            if entry["toolchain"] == "rust":
                continue
            evidence = self.directory / "probe.json"
            script = (
                "import json, subprocess; from pathlib import Path; "
                "r = subprocess.run(['rustc', '--version'], capture_output=True, text=True); "
                f"Path({str(evidence)!r}).write_text(json.dumps([r.returncode, r.stdout]))"
            )
            with self.subTest(implementation=entry["implementation"]):
                with patch.dict(os.environ, {"PATH": str(self.bin)}):
                    self.assertEqual(
                        ci.run_isolated(entry["implementation"], [sys.executable, "-c", script]), 0
                    )
                self.assertEqual(json.loads(evidence.read_text()), [127, ""])

    def test_optional_probe_cannot_allow_compilation_or_additional_arguments(self):
        for arguments in (["input.rs"], ["--version", "input.rs"], ["-V"], []):
            script = (
                f"import subprocess; subprocess.run({['rustc', *arguments]!r}, capture_output=True)"
            )
            with self.subTest(arguments=arguments):
                with patch.dict(os.environ, {"PATH": str(self.bin)}):
                    with self.assertRaisesRegex(RuntimeError, "undeclared host toolchain.*rustc"):
                        ci.run_isolated("python-flask", [sys.executable, "-c", script])

    def test_guard_exit_and_diagnostics_identify_the_undeclared_command(self):
        evidence = self.directory / "guard.json"
        script = (
            "import json, subprocess; from pathlib import Path; "
            "r = subprocess.run(['go'], capture_output=True, text=True); "
            f"Path({str(evidence)!r}).write_text(json.dumps([r.returncode, r.stderr]))"
        )
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            with self.assertRaisesRegex(RuntimeError, "undeclared host toolchain.*go"):
                ci.run_isolated("python-fastapi", [sys.executable, "-c", script])
        status, message = json.loads(evidence.read_text())
        self.assertEqual(status, 127)
        self.assertIn("undeclared host toolchain: go", message)

    def test_child_failure_is_preserved_and_path_and_temporary_files_are_restored(self):
        output = self.directory / "path.txt"
        script = (
            "import os,sys; from pathlib import Path; "
            f"Path({str(output)!r}).write_text(os.environ['PATH'].split(os.pathsep)[0]); "
            "sys.exit(7)"
        )
        before = os.environ.get("PATH")
        self.assertEqual(ci.run_isolated("go-gin", [sys.executable, "-c", script]), 7)
        self.assertEqual(os.environ.get("PATH"), before)
        self.assertFalse(Path(output.read_text()).exists())

    def test_unknown_implementation_and_empty_command_fail_before_execution(self):
        marker = self.directory / "should-not-exist"
        command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
        with self.assertRaisesRegex(RuntimeError, "unknown implementation"):
            ci.run_isolated("unknown-framework", command)
        with self.assertRaisesRegex(RuntimeError, "command"):
            ci.run_isolated("go-gin", [])
        self.assertFalse(marker.exists())

    def test_cli_preserves_argument_boundaries_and_child_exit_status(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmark.ci",
                "run-isolated",
                "--implementation",
                "go-gin",
                "--",
                sys.executable,
                "-c",
                "import sys; assert sys.argv[1] == 'two words'; sys.exit(7)",
                "two words",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cli_rejects_missing_command_and_unknown_implementation(self):
        for args in (
            ["--implementation", "go-gin"],
            ["--implementation", "unknown-framework", "--", "true"],
        ):
            result = subprocess.run(
                [sys.executable, "-m", "benchmark.ci", "run-isolated", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("CI validation failed:", result.stderr)


if __name__ == "__main__":
    unittest.main()
