"""Exercise Pages trust decisions without credentials, network calls or deployments."""

import copy
import importlib
import json
import unittest
from pathlib import Path

from benchmark.results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "tappe9/simple-api-benchmark"
HEAD = "b" * 40
WORKFLOW = REPOSITORY + "/.github/workflows/pages.yml@refs/heads/main"


class PagesContextTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / "results/latest.json").read_bytes())
        self.env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": HEAD,
            "GITHUB_WORKFLOW_SHA": HEAD,
            "GITHUB_WORKFLOW_REF": WORKFLOW,
            "GITHUB_EVENT_NAME": "workflow_run",
        }
        self.event = {
            "repository": {"full_name": REPOSITORY, "default_branch": "main"},
            "workflow_run": {
                "name": "CI",
                "path": ".github/workflows/ci.yml",
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "head_sha": HEAD,
                "head_branch": "main",
                "head_repository": {"full_name": REPOSITORY},
            },
        }

    def validate(self, *, parents=(), changed=(), report=None, head=HEAD):
        try:
            module = importlib.import_module("benchmark.pages")
        except ModuleNotFoundError:
            self.fail("benchmark.pages must enforce the tested trusted-main boundary")
        return module.validate_event(
            self.env, self.event, head=head, parents=parents, changed=changed, report=report
        )

    def official(self):
        context = self.report["metadata"]["github"]
        self.event["workflow_run"].update(
            name="Official benchmark",
            path=".github/workflows/benchmark.yml",
            event=context["event"],
            head_sha=context["source_commit"],
            id=int(context["run_id"]),
            run_attempt=int(context["run_attempt"]),
        )
        return {
            "parents": [context["source_commit"]],
            "changed": [
                "README.md",
                "README.ja.md",
                "results/latest.json",
                "results/history/test-publication.json",
            ],
            "report": self.report,
        }

    def test_successful_main_push_ci_and_explicit_main_dispatch_are_accepted(self):
        self.validate()
        self.env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        del self.event["workflow_run"]
        self.validate()

    def test_untrusted_missing_and_mismatched_execution_contexts_are_rejected(self):
        changes = {
            "GITHUB_ACTIONS": "false",
            "GITHUB_REPOSITORY": "fork/simple-api-benchmark",
            "GITHUB_REF": "refs/heads/feature",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_WORKFLOW_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": WORKFLOW.replace("main", "feature"),
            "GITHUB_EVENT_NAME": "pull_request",
        }
        original = self.env.copy()
        for key, value in changes.items():
            self.env = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                self.validate()
        for key in original:
            self.env = {k: v for k, v in original.items() if k != key}
            with self.subTest(missing=key), self.assertRaises(BenchmarkFailure):
                self.validate()
        self.env = original
        with self.assertRaises(BenchmarkFailure):
            self.validate(head="a" * 40)
        self.event["repository"]["default_branch"] = "other"
        with self.assertRaises(BenchmarkFailure):
            self.validate()

    def test_pr_fork_failed_pending_stale_and_renamed_workflows_cannot_trigger_pages(self):
        original = copy.deepcopy(self.event)
        for key, value in {
            "event": "pull_request",
            "conclusion": "failure",
            "status": "in_progress",
            "head_sha": "a" * 40,
            "head_branch": "feature",
            "head_repository": {"full_name": "attacker/fork"},
            "name": "Unrelated workflow",
            "path": ".github/workflows/untrusted.yml",
        }.items():
            self.event = copy.deepcopy(original)
            self.event["workflow_run"][key] = value
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                self.validate()

    def test_official_success_requires_its_exact_run_and_single_publication_only_commit(self):
        arguments = self.official()
        self.validate(**arguments)
        for changes in (
            {"parents": ["a" * 40]},
            {"parents": [arguments["parents"][0], "a" * 40]},
            {"changed": [*arguments["changed"], "site/app.mjs"]},
            {"changed": arguments["changed"][:-1]},
            {"report": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(BenchmarkFailure):
                self.validate(**{**arguments, **changes})
        for key, value in (("id", 1), ("run_attempt", 99), ("event", "pull_request")):
            old = self.event["workflow_run"][key]
            self.event["workflow_run"][key] = value
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                self.validate(**arguments)
            self.event["workflow_run"][key] = old

    def test_an_invalid_report_never_authorizes_an_official_publication_event(self):
        arguments = self.official()
        self.report["official"] = False
        with self.assertRaises(BenchmarkFailure):
            self.validate(**arguments)


    def test_missing_or_malformed_upstream_repository_is_a_controlled_rejection(self):
        for repository in (None, [], "foreign", {}):
            self.event["workflow_run"]["head_repository"] = repository
            with self.subTest(repository=repository), self.assertRaises(BenchmarkFailure):
                self.validate()


if __name__ == "__main__":
    unittest.main()
