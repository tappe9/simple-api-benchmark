"""Parse actual workflow YAML to verify the read/write and trusted-source boundaries."""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / ".github/workflows" / name
    if not path.exists():
        return {}
    # BaseLoader deliberately preserves YAML 1.2 Actions keys such as `on` and bool strings.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_only_two_permanent_workflows_with_pinned_actions_and_no_persisted_credentials(self):
        paths = list((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual({p.name for p in paths}, {"ci.yml", "benchmark.yml"})
        for path in paths:
            workflow = load(path.name)
            self.assertEqual(workflow["permissions"], {"contents": "read"})
            for job in workflow["jobs"].values():
                self.assertEqual(job["runs-on"], "ubuntu-24.04")
                self.assertGreater(int(job["timeout-minutes"]), 0)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^actions/[a-z-]+@[0-9a-f]{40}$")
                        if step["uses"].startswith("actions/checkout@"):
                            self.assertEqual(step["with"]["persist-credentials"], "false")
                    self.assertNotIn("${{", step.get("run", ""), "pass expression data through env")

    def test_pr_ci_is_read_only_all_gates_and_smoke_never_publish(self):
        ci = load("ci.yml")
        self.assertIn("pull_request", ci.get("on", {}))
        self.assertEqual(set(ci["on"]), {"pull_request", "push"})
        self.assertEqual(ci["on"]["push"]["branches"], ["main"])
        self.assertEqual(
            set(ci["on"]["push"]["paths-ignore"]), {"results/**", "README.md", "README.ja.md"}
        )
        content = (ROOT / ".github/workflows/ci.yml").read_text()
        for forbidden in (
            "secrets.",
            "contents: write",
            "pull_request_target",
            "workflow_run",
            "benchmark.official",
            "benchmark.publish",
        ):
            self.assertNotIn(forbidden, content)
        for target in (
            "test-db",
            "test-go-gin",
            "test-rust-actix",
            "test-node-fastify",
            "test-python-fastapi",
            "test-contract",
            "test-benchmark",
            "benchmark-smoke",
        ):
            self.assertIn("make " + target, content)
        uploads = [
            step
            for job in ci["jobs"].values()
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        ]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["with"]["path"], ".cache/ci/format.patch")
        self.assertIn("git diff --exit-code HEAD", content)
        self.assertIn("actionlint", content)
        self.assertIn("test_workflows.py", content)

    def test_official_workflow_has_no_pr_or_push_trigger_and_only_default_ref(self):
        workflow = load("benchmark.yml")
        self.assertEqual(set(workflow.get("on", {})), {"schedule", "workflow_dispatch"})
        self.assertEqual(workflow["on"]["schedule"], [{"cron": "27 14 * * 6"}])
        self.assertIn(workflow["on"]["workflow_dispatch"], ("", {}))
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(set(workflow["jobs"]), {"measure", "publish"})
        for job in workflow["jobs"].values():
            self.assertIn("github.event.repository.default_branch", job["if"])
            self.assertIn("github.ref", job["if"])
            self.assertIn("tappe9/simple-api-benchmark", job["if"])
            checkout = next(
                s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
            )
            self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")

    def test_measurement_is_one_read_only_job_using_existing_runner(self):
        workflow = load("benchmark.yml")
        self.assertIn("measure", workflow.get("jobs", {}))
        job = workflow["jobs"]["measure"]
        self.assertNotIn("strategy", job)
        self.assertEqual(job.get("permissions", {"contents": "read"}), {"contents": "read"})
        steps = job["steps"]
        self.assertEqual(sum("python -m benchmark.official" in s.get("run", "") for s in steps), 1)
        content = str(job)
        self.assertNotIn("secrets.", content)
        self.assertNotIn("-z 30s", content)
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"], ".cache/official/")
        self.assertEqual(upload["with"]["include-hidden-files"], "true")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_only_successful_same_run_artifact_reaches_write_job(self):
        workflow = load("benchmark.yml")
        self.assertIn("publish", workflow.get("jobs", {}))
        job = workflow["jobs"]["publish"]
        self.assertEqual(job["needs"], "measure")
        self.assertIn("needs.measure.result == 'success'", job["if"])
        self.assertEqual(job["permissions"], {"contents": "write"})
        download = next(
            s for s in job["steps"] if s.get("uses", "").startswith("actions/download-artifact@")
        )
        self.assertEqual(set(download["with"]), {"name", "path"})
        upload = next(
            s
            for s in workflow["jobs"]["measure"]["steps"]
            if s.get("uses", "").startswith("actions/upload-artifact@")
        )
        self.assertEqual(upload["with"]["name"], download["with"]["name"])
        self.assertIn("github.run_id", download["with"]["name"])
        self.assertIn("github.run_attempt", download["with"]["name"])
        final = job["steps"][-1]
        self.assertEqual(final["run"], "python -m benchmark.publish")
        self.assertEqual(final["env"], {"GH_TOKEN": "${{ github.token }}"})
        for step in job["steps"][:-1]:
            self.assertNotIn("GH_TOKEN", str(step))
        self.assertNotRegex(str(job), re.compile(r"make (test|benchmark)|docker (build|run)|npm "))


if __name__ == "__main__":
    unittest.main()
