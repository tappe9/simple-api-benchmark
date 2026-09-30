"""Keep JVM diagnostic execution separate from automatic CI, without extra dependencies."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/jvm-diagnostic.yml"


class JvmDiagnosticWorkflowSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), "JVM diagnosis needs its own manual-only workflow")
        self.source = WORKFLOW.read_text()

    def test_one_bounded_diagnostic_command_leaves_time_for_failure_artifacts(self):
        commands = re.findall(r"^\s+run: (.+)$", self.source, flags=re.MULTILINE)
        self.assertEqual(
            commands,
            ["timeout --signal=TERM --kill-after=120s 104m python -m benchmark.jvm_diagnostic"],
        )
        self.assertIn("    timeout-minutes: 120\n", self.source)
        self.assertNotIn("continue-on-error", self.source)

    def test_kill_grace_covers_cleanup_within_the_total_job_budget(self):
        command = re.search(
            r"^\s+run: timeout --signal=TERM --kill-after=(\d+)s (\d+)m ",
            self.source,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(command)
        kill_seconds, run_minutes = map(int, command.groups())
        # Failure logs (15s), Compose down (60s), and three resource checks (10s each).
        cleanup_seconds = 15 + 60 + 3 * 10
        self.assertGreater(kill_seconds, cleanup_seconds, "leave time to journal cleanup")
        step_caps = list(
            map(int, re.findall(r"^        timeout-minutes: (\d+)$", self.source, re.MULTILINE))
        )
        self.assertEqual(step_caps, [3, 3, 7])
        job_minutes = re.search(r"^    timeout-minutes: (\d+)$", self.source, re.MULTILINE)
        self.assertIsNotNone(job_minutes)
        total_seconds = (sum(step_caps) + run_minutes) * 60 + kill_seconds
        self.assertEqual(total_seconds, 119 * 60)
        self.assertLess(total_seconds, int(job_minutes.group(1)) * 60)

    def test_diagnostic_has_no_automatic_trigger_or_user_controlled_profile(self):
        trigger = re.search(r"^on:\n(.*?)(?=^\S)", self.source, flags=re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.group(1), "  workflow_dispatch:\n")

    def test_automatic_workflows_never_invoke_the_jvm_load_diagnostic(self):
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            if workflow == WORKFLOW:
                continue
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text()
                self.assertNotIn("benchmark.jvm_diagnostic", source)
                self.assertNotIn("make jvm-diagnostic", source)
                self.assertNotIn("./.github/workflows/jvm-diagnostic.yml", source)

    def test_diagnostic_cannot_publish_or_write_repository_credentials(self):
        for forbidden in (
            "contents: write",
            "pages: write",
            "id-token: write",
            "secrets.",
            "github.token",
            "benchmark.official",
            "benchmark.publish",
            "deploy-pages",
            "git push",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)


if __name__ == "__main__":
    unittest.main()
