"""Real subprocess safety, not Docker or benchmark measurements."""

import contextlib
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from benchmark.process import execute
from benchmark.results import BenchmarkFailure


class ProcessTests(unittest.TestCase):
    def test_capture_output_and_report_failure(self):
        self.assertEqual(
            execute([sys.executable, "-c", "print('hello')"], timeout=5).strip(), "hello"
        )
        with self.assertRaisesRegex(BenchmarkFailure, "diagnostic"):
            execute([sys.executable, "-c", "import sys; sys.exit('diagnostic')"], timeout=5)

    def test_missing_command_is_actionable(self):
        with self.assertRaisesRegex(BenchmarkFailure, "cannot execute"):
            execute(["/nonexistent-benchmark-command"], timeout=1)

    def test_tick_failure_stops_running_command(self):
        def fail():
            raise BenchmarkFailure("metric unavailable")

        start = time.monotonic()
        with self.assertRaisesRegex(BenchmarkFailure, "metric unavailable"):
            execute([sys.executable, "-c", "import time; time.sleep(30)"], timeout=5, tick=fail)
        self.assertLess(time.monotonic() - start, 3)

    @unittest.skipUnless(sys.platform == "linux", "Linux /proc process liveness assertion")
    def test_timeout_kills_descendant_and_reaps_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            source = (
                "import pathlib, subprocess, sys, time; "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(30)"
            )
            with self.assertRaisesRegex(BenchmarkFailure, "timeout"):
                execute([sys.executable, "-c", source], timeout=3)
            pid = int(pidfile.read_text())
            for _ in range(50):
                stat = Path(f"/proc/{pid}/stat")
                if not stat.exists() or stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.02)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail("timed out subprocess left a running child")
            # No unreaped direct child remains. Orphan zombies belong to the host init.
            with self.assertRaises(ChildProcessError):
                os.waitpid(-1, os.WNOHANG)

    def test_handled_interruption_kills_process_group(self):
        def interrupt():
            raise KeyboardInterrupt("handled interruption")

        with self.assertRaises(KeyboardInterrupt):
            execute(
                [sys.executable, "-c", "import time; time.sleep(30)"], timeout=5, tick=interrupt
            )
        with self.assertRaises(ChildProcessError):
            os.waitpid(-1, os.WNOHANG)

    def test_large_output_does_not_deadlock(self):
        output = execute([sys.executable, "-c", "print('x' * 100000)"], timeout=5)
        self.assertEqual(len(output.strip()), 100000)


class FailedParentTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux /proc process liveness assertion")
    def test_failed_parent_does_not_leave_running_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            source = (
                "import pathlib, subprocess, sys; "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); sys.exit(1)"
            )
            try:
                with self.assertRaises(BenchmarkFailure):
                    execute([sys.executable, "-c", source], timeout=10)
                pid = int(pidfile.read_text())
                for _ in range(50):
                    stat = Path(f"/proc/{pid}/stat")
                    if not stat.exists() or stat.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("failed command left a running descendant")
            finally:
                if pidfile.exists():
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
