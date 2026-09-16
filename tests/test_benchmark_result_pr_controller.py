"""Stateful external-service model plus real Git, not a GitHub ruleset proof."""

import contextlib
import copy
import importlib
import io
import json
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import unquote

import test_benchmark_publication_manifest as manifest
from test_benchmark_publication import context, context_env
from test_benchmark_result_pr_checks import ci_evidence, effective_rules, pull_request

from benchmark.github_api import APIError
from benchmark.publish import prepare_candidate
from benchmark.results import BenchmarkFailure


class GitHubModel:
    """Only the remote API is modeled; commits and ref updates use real local Git."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.candidate = fixture.candidate
        self.pr = None
        self.run, self.jobs, self.check = ci_evidence(self.candidate)
        self.rules = effective_rules()
        self.post_count = 0
        self.put_count = 0
        self.lose_create_response = False
        self.lose_merge_response = False
        self.advance_during_merge = False
        self.deny_merge = False
        self.no_runs = False

    def pages(self, path, key=None):
        if path.startswith("pulls?"):
            return [] if self.pr is None else [copy.deepcopy(self.pr)]
        if path.startswith("actions/workflows/ci.yml/runs?"):
            return [] if self.no_runs else [copy.deepcopy(self.run)]
        if path == "actions/runs/900/attempts/1/jobs":
            return copy.deepcopy(self.jobs)
        if path == "rules/branches/main":
            return copy.deepcopy(self.rules)
        raise AssertionError(path)

    def main(self):
        return self.fixture.git("rev-parse", "refs/heads/main", cwd=self.fixture.remote)

    def advance(self):
        f = self.fixture
        commit = f.git(
            "commit-tree",
            self.candidate.source_tree,
            "-p",
            self.main(),
            "-m",
            "synthetic concurrent code change",
        )
        f.git("push", "-q", "origin", commit + ":refs/heads/main")
        return commit

    def request(self, method, path, body=None):
        f = self.fixture
        if method == "GET" and path.startswith("git/ref/heads/"):
            ref = "refs/heads/" + unquote(path.removeprefix("git/ref/heads/"))
            # Check listing instead of treating arbitrary Git failures as missing refs.
            listed = f.git("for-each-ref", "--format=%(refname) %(objectname)", ref, cwd=f.remote)
            if not listed:
                raise APIError(404)
            name, sha = listed.split()
            if name != ref:
                raise AssertionError(listed)
            return {"ref": ref, "object": {"sha": sha, "type": "commit"}}
        if method == "GET" and path == "pulls/63":
            if self.pr is None:
                raise APIError(404)
            return copy.deepcopy(self.pr)
        if method == "GET" and path == "check-runs/1003":
            return copy.deepcopy(self.check)
        if method == "GET" and path.startswith("git/commits/"):
            sha = path.split("/")[-1]
            return {
                "sha": sha,
                "tree": {"sha": f.git("rev-parse", sha + "^{tree}")},
                "parents": [
                    {"sha": s} for s in f.git("rev-list", "--parents", "-1", sha).split()[1:]
                ],
            }
        if method == "POST" and path == "pulls":
            self.post_count += 1
            assert body["head"] == self.candidate.branch and body["base"] == "main"
            self.pr = pull_request(self.candidate)
            if self.lose_create_response:
                raise APIError(None)
            return copy.deepcopy(self.pr)
        if method == "PUT" and path == "pulls/63/merge":
            self.put_count += 1
            assert body["sha"] == self.candidate.sha and body["merge_method"] == "squash"
            if self.deny_merge:
                raise APIError(403)
            if self.advance_during_merge:
                self.advance()
            # This simulates strict protection. Real GitHub enforcement still needs rollout evidence.
            if self.main() != self.candidate.source or self.pr["head"]["sha"] != body["sha"]:
                raise APIError(405)
            sha = f.git(
                "commit-tree",
                self.candidate.tree,
                "-p",
                self.main(),
                "-m",
                "synthetic reviewed squash",
            )
            f.git("push", "-q", "origin", sha + ":refs/heads/main")
            self.pr.update(state="closed", merged=True, merge_commit_sha=sha)
            if self.lose_merge_response:
                raise APIError(None)
            return {"sha": sha, "merged": True}
        raise AssertionError((method, path))


class ControllerTests(unittest.TestCase):
    setUpRepo = manifest.PublicationManifestIntegrationTests.setUp
    git = manifest.PublicationManifestIntegrationTests.git

    def setUp(self):
        self.setUpRepo()
        self.candidate = prepare_candidate(
            self.report, self.repo, expected_context=context(self.source)
        )
        self.api = GitHubModel(self)

    def module(self):
        try:
            return importlib.import_module("benchmark.result_pr")
        except ModuleNotFoundError:
            self.fail("result-PR controller required")

    def propose(self):
        return self.module().propose(self.repo, self.candidate, self.api, self.api)

    def merge(self):
        return self.module().merge(self.candidate, 63, self.api, self.api, ruleset_id=99)

    def test_proposal_is_idempotent_and_does_not_publish(self):
        self.assertEqual(self.propose(), 63)
        self.assertEqual(self.propose(), 63)
        self.assertEqual(self.api.post_count, 1)
        self.assertEqual(self.api.main(), self.source)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/" + self.candidate.branch, cwd=self.remote),
            self.candidate.sha,
        )

    def test_successful_squash_preserves_audited_tree_parent_and_retry_identity(self):
        self.propose()
        result = self.merge()
        self.assertEqual(self.api.main(), result)
        self.assertEqual(
            self.git("rev-list", "--parents", "-1", result).split(), [result, self.source]
        )
        self.assertEqual(self.git("rev-parse", result + "^{tree}"), self.candidate.tree)
        self.assertEqual(self.merge(), result)
        self.assertEqual(self.propose(), 63)
        self.assertEqual(self.api.put_count, 1)

    def test_lost_write_responses_are_reconciled_without_duplicate_writes(self):
        self.api.lose_create_response = True
        self.propose()
        self.api.lose_merge_response = True
        result = self.merge()
        self.assertEqual(self.merge(), result)
        self.assertEqual((self.api.post_count, self.api.put_count), (1, 1))

    def test_stale_main_or_modified_pr_never_reaches_merge_write(self):
        self.propose()
        self.api.pr["head"]["sha"] = "f" * 40
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.api.pr = pull_request(self.candidate)
        advanced = self.api.advance()
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.assertEqual(self.api.put_count, 0)
        self.assertEqual(self.api.main(), advanced)

    def test_failed_incomplete_or_wrong_issuer_ci_never_merges(self):
        self.propose()
        original = copy.deepcopy(self.api.jobs)
        for conclusion in ("failure", "cancelled", "skipped", "neutral", None):
            self.api.jobs[0]["conclusion"] = conclusion
            with self.subTest(conclusion=conclusion), self.assertRaises(BenchmarkFailure):
                self.merge()
        self.api.jobs = original[:-1]
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.api.jobs = original
        self.api.check["app"]["id"] = 1
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.assertEqual(self.api.put_count, 0)
        self.assertEqual(self.api.main(), self.source)

    def test_missing_policy_cannot_be_replaced_by_green_ci(self):
        self.propose()
        self.api.rules = []
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.assertEqual(self.api.put_count, 0)

    def test_merge_denial_and_concurrent_main_update_have_no_direct_push_fallback(self):
        self.propose()
        self.api.deny_merge = True
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.assertEqual(self.api.main(), self.source)
        self.api.deny_merge = False
        self.api.advance_during_merge = True
        with self.assertRaises(BenchmarkFailure):
            self.merge()
        self.assertNotEqual(self.api.main(), self.candidate.sha)
        self.assertNotEqual(self.api.main(), self.source)
        self.assertFalse(self.api.pr["merged"])
        self.assertEqual(self.api.put_count, 2)

    def test_ci_wait_is_bounded_and_read_only(self):
        self.propose()
        self.api.no_runs = True
        slept = []
        with self.assertRaisesRegex(BenchmarkFailure, "timed out"):
            self.module().wait(self.candidate, 63, self.api, polls=2, sleep=slept.append)
        self.assertEqual(len(slept), 1)
        self.assertEqual(self.api.put_count, 0)
        self.api.no_runs = False
        self.assertEqual(self.module().wait(self.candidate, 63, self.api, polls=1), 900)

    def test_unknown_or_unapproved_modes_are_fail_closed(self):
        module = self.module()
        self.assertEqual(module.publication_mode({}), "legacy")
        self.assertEqual(module.publication_mode({"RESULT_PUBLICATION_MODE": "legacy"}), "legacy")
        for env in (
            {"RESULT_PUBLICATION_MODE": "typo"},
            {"RESULT_PUBLICATION_MODE": "pull-request-v1"},
            {"RESULT_PUBLICATION_MODE": "pull-request-v1", "RESULT_PR_ROLLOUT_APPROVED": "yes"},
        ):
            with self.subTest(env=env), self.assertRaises(BenchmarkFailure):
                module.publication_mode(env)
        self.assertEqual(
            module.publication_mode(
                {
                    "RESULT_PUBLICATION_MODE": "pull-request-v1",
                    "RESULT_PR_ROLLOUT_APPROVED": "strict-main-v1",
                    "RESULT_PR_RULESET_ID": "99",
                }
            ),
            "pull-request-v1",
        )

    def test_newest_ci_run_is_used_instead_of_an_older_success(self):
        module = self.module()
        reader = Mock()
        reader.pages.return_value = [
            self.api.run,
            {**self.api.run, "id": 901, "conclusion": "failure"},
        ]
        self.assertEqual(module.ci_run(reader, self.candidate)["id"], 901)

    def test_cli_preflight_rejects_untrusted_context_before_api_access(self):
        module = self.module()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(module, "GitHubAPI") as api,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(module.main(["preflight"]), 1)
            api.assert_not_called()

    def test_cli_preflight_records_legacy_mode_without_a_write_client(self):
        module = self.module()
        output = self.repo / ".cache/output"
        output.write_text("")
        env = {**context_env(self.source), "GITHUB_OUTPUT": str(output)}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(module, "GitHubAPI") as api,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(module.main(["preflight"]), 0)
            self.assertEqual(output.read_text(), "mode=legacy\nproducer_run_attempt=1\n")
            api.assert_not_called()

    def test_cli_wait_uses_original_attempt_and_never_requests_a_write_token(self):
        module = self.module()
        self.propose()
        self.git(
            "remote", "set-url", "origin", "https://github.com/tappe9/simple-api-benchmark.git"
        )
        (self.repo / ".cache/official/selected.json").write_text(json.dumps(self.report))
        env = {
            **context_env(self.source),
            "GITHUB_RUN_ATTEMPT": "2",
            "PUBLICATION_ATTEMPT": "1",
            "RESULT_PUBLICATION_MODE": "pull-request-v1",
            "RESULT_PR_RULESET_ID": "99",
            "RESULT_PR_ROLLOUT_APPROVED": "strict-main-v1",
            "RESULT_PR_NUMBER": "63",
            "GH_READ_TOKEN": "read-only-test-token",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(module, "ROOT", self.repo),
            patch.object(module, "GitHubAPI", return_value=self.api) as api,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(module.main(["wait"]), 0)
            api.assert_called_once_with("read-only-test-token")
        self.assertEqual(self.api.put_count, 0)

    def test_closed_unmerged_and_changed_branches_are_not_reopened_or_overwritten(self):
        self.propose()
        self.api.pr.update(state="closed", merged=False)
        with self.assertRaises(BenchmarkFailure):
            self.propose()
        self.assertEqual(self.api.post_count, 1)
        self.assertEqual(self.api.put_count, 0)

    def test_eight_stack_candidate_uses_the_same_pr_transaction(self):
        from registry_fixtures import real_eight_report

        self.report = real_eight_report(self.report, self.repo)
        self.candidate = prepare_candidate(
            self.report, self.repo, expected_context=context(self.source)
        )
        self.api = GitHubModel(self)
        self.propose()
        result = self.merge()
        published = json.loads(self.git("show", result + ":results/latest.json"))
        self.assertEqual(len(published["implementations"]), 8)
        self.assertEqual(published, self.report)


if __name__ == "__main__":
    unittest.main()
