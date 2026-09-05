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
    def test_only_three_permanent_workflows_use_pinned_actions_and_safe_checkouts(self):
        paths = list((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual({p.name for p in paths}, {"ci.yml", "benchmark.yml", "pages.yml"})
        for path in paths:
            workflow = load(path.name)
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
        self.assertEqual(ci["permissions"], {"contents": "read"})
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
            "deploy-pages",
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
            "test-site",
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
        self.assertEqual(workflow["permissions"], {"contents": "read"})
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

    def test_pages_deploys_only_after_trusted_main_validation(self):
        workflow = load("pages.yml")
        self.assertEqual(set(workflow.get("on", {})), {"workflow_run", "workflow_dispatch"})
        self.assertEqual(
            set(workflow["on"]["workflow_run"]["workflows"]), {"CI", "Official benchmark"}
        )
        self.assertEqual(workflow["on"]["workflow_run"]["types"], ["completed"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"build", "deploy", "release"})
        build = workflow["jobs"]["build"]
        self.assertEqual(build.get("permissions", {"contents": "read"}), {"contents": "read"})
        self.assertIn("python -m benchmark.pages", str(build))
        self.assertIn("python -m benchmark.site", str(build))
        upload = next(
            step
            for step in build["steps"]
            if step.get("uses", "").startswith("actions/upload-pages-artifact@")
        )
        self.assertEqual(upload["with"]["path"], ".cache/site")
        deploy = workflow["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "build")
        self.assertEqual(deploy["permissions"], {"pages": "write", "id-token": "write"})
        self.assertEqual(deploy["environment"]["name"], "github-pages")
        self.assertTrue(
            any(
                step.get("uses", "").startswith("actions/deploy-pages@") for step in deploy["steps"]
            )
        )
        content = (ROOT / ".github/workflows/pages.yml").read_text()
        for forbidden in ("pull_request:", "pull_request_target", "secrets."):
            self.assertNotIn(forbidden, content)

    def test_v0_1_0_release_is_after_pages_and_only_from_successful_main_ci(self):
        workflow = load("pages.yml")
        release = workflow["jobs"]["release"]
        self.assertEqual(release["needs"], "deploy")
        self.assertEqual(release["permissions"], {"contents": "write"})
        condition = release["if"]
        for expected in (
            "github.event_name == 'workflow_run'",
            "github.event.workflow_run.name == 'CI'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_sha == github.sha",
            "github.event.workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(expected, condition)
        self.assertEqual(len(release["steps"]), 1)
        step = release["steps"][0]
        self.assertEqual(step["env"], {"GH_TOKEN": "${{ github.token }}"})
        command = step["run"]
        self.assertIn("gh release view v0.1.0", command)
        self.assertIn("gh release create v0.1.0", command)
        self.assertIn('--target "$GITHUB_SHA"', command)
        self.assertIn("GitHub-hosted runners are shared", command)
        self.assertNotIn("${{", command)


if __name__ == "__main__":
    unittest.main()
