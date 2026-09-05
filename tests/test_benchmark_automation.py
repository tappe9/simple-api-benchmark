"""Exercise the official wrapper with the real runner and isolated synthetic I/O."""

import copy
import io
import json
import signal
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_benchmark_publication import context_env, synthetic_report

from benchmark import official, run
from benchmark.generate_readme import render
from benchmark.results import BenchmarkFailure


class OfficialWrapperTests(unittest.TestCase):
    def exercise(self, failure=None):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            report = synthetic_report(root)
            latest = root / "results/latest.json"
            latest.parent.mkdir()
            latest.write_bytes(b"previous verified bytes")
            cleaned = []
            measured = []

            class Environment:
                artifacts = root / report["metadata"]["artifact_directory"]

                def build(self, implementation):
                    self.backend = next(
                        b
                        for b in report["implementations"]
                        if b["implementation"] == implementation
                    )

                def start(self, implementation):
                    return copy.deepcopy(self.backend["container"])

                def check(self):
                    pass

                def measure(self, endpoint, duration, index):
                    measured.append((self.backend["implementation"], endpoint, duration, index))
                    if failure == "late" and measured[-1] == ("python-fastapi", "/cpu", 30, 3):
                        raise BenchmarkFailure("injected last-run failure")
                    if index:
                        entry = next(
                            e for e in self.backend["endpoints"] if e["endpoint"] == endpoint
                        )
                        return copy.deepcopy(entry["runs"][index - 1])

                def cleanup(self):
                    cleaned.append(self.backend["implementation"])
                    if failure == "cleanup" and len(cleaned) == 4:
                        raise BenchmarkFailure("injected final cleanup failure")

            if failure == "raw":
                next(Environment.artifacts.glob("*-run-3.json")).write_text("{}")
            stack.enter_context(patch.object(official, "ROOT", root))
            stack.enter_context(patch.dict("os.environ", context_env(), clear=True))
            stack.enter_context(
                patch.object(official, "ensure_oha", return_value=Path("synthetic"))
            )
            stack.enter_context(
                patch.object(official, "provenance", return_value=copy.deepcopy(report["metadata"]))
            )
            stack.enter_context(
                patch.object(official, "runner_metadata", return_value=report["metadata"]["runner"])
            )
            stack.enter_context(patch.object(official, "execute", return_value="synthetic-version"))
            stack.enter_context(
                patch.object(official, "DockerEnvironment", return_value=Environment())
            )
            stack.enter_context(patch.object(run, "run_contract", return_value=14))
            stack.enter_context(
                patch.object(run, "now", side_effect=[report["started_at"], report["completed_at"]])
            )
            previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = official.main()
            self.assertEqual(previous, {sig: signal.getsignal(sig) for sig in previous})
            self.assertEqual(latest.read_bytes(), b"previous verified bytes")
            self.assertEqual(cleaned, list(run.IMPLEMENTATIONS))
            selected = root / ".cache/official/selected.json"
            if failure:
                self.assertEqual(code, 1)
                self.assertFalse(selected.exists())
            else:
                self.assertEqual(code, 0)
                actual = json.loads(selected.read_text())
                self.assertIs(actual["official"], True)
                self.assertEqual(actual["mode"], "official")
                self.assertEqual(actual["conditions"], run.PROFILE)
                self.assertEqual(actual["implementations"], report["implementations"])
                self.assertEqual(len([m for m in measured if m[-1] != 0]), 36)
                candidate = json.loads(selected.with_name("candidate.json").read_text())
                self.assertIs(candidate["official"], False)
                self.assertEqual(candidate["mode"], "local")

    def test_existing_runner_is_reused_and_only_audited_complete_report_is_selected(self):
        self.exercise()

    def test_final_measurement_cleanup_and_raw_audit_failures_leave_no_selected_result(self):
        for failure in ("late", "cleanup", "raw"):
            with self.subTest(failure=failure):
                self.exercise(failure)

    def test_rendered_sections_are_whitespace_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            report = synthetic_report(Path(directory))
            for locale in ("en", "ja"):
                for line in render(report, locale).splitlines():
                    self.assertEqual(line, line.rstrip())


if __name__ == "__main__":
    unittest.main()
