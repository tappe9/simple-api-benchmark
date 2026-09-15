"""Regression tests for Pages upstream eligibility and concurrency placement."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_pages():
    return yaml.load(
        (ROOT / ".github/workflows/pages.yml").read_text(),
        Loader=yaml.BaseLoader,
    )


class PagesWorkflowEligibilityTests(unittest.TestCase):
    def test_build_filters_ineligible_upstream_runs_before_privileged_work(self):
        workflow = load_pages()
        condition = workflow["jobs"]["deploy"]["if"]

        for expected in (
            "github.repository == 'tappe9/simple-api-benchmark'",
            "github.event_name == 'workflow_dispatch'",
            "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)",
            "github.event_name == 'workflow_run'",
            "github.event.workflow_run.status == 'completed'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_branch == github.event.repository.default_branch",
            "github.event.workflow_run.head_repository.full_name == github.repository",
            "github.event.workflow_run.name == 'CI'",
            "github.event.workflow_run.path == '.github/workflows/ci.yml'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.head_sha == github.sha",
        ):
            self.assertIn(expected, condition)

    def test_only_an_eligible_deploy_job_acquires_pages_concurrency(self):
        workflow = load_pages()
        self.assertNotIn("concurrency", workflow)
        self.assertNotIn("concurrency", workflow["jobs"]["deploy"])
        workflow = yaml.load(
            (ROOT / ".github/workflows/pages-deploy.yml").read_text(), Loader=yaml.BaseLoader
        )
        self.assertNotIn("concurrency", workflow["jobs"]["build"])

        deploy = workflow["jobs"]["deploy"]
        self.assertEqual(
            deploy["concurrency"],
            {"group": "pages", "cancel-in-progress": "false"},
        )
        self.assertEqual(deploy["needs"], "build")


if __name__ == "__main__":
    unittest.main()
