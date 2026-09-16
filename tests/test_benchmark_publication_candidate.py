"""Candidate preparation uses actual temporary Git repositories and synthetic reports."""

import copy
import importlib
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_benchmark_publication as fixtures
from test_benchmark_publication import context

from benchmark import publish
from benchmark.results import BenchmarkFailure


class CandidateTests(unittest.TestCase):
    setUp = fixtures.GitPublicationTests.setUp
    git = fixtures.GitPublicationTests.git
    remote_head = fixtures.GitPublicationTests.remote_head

    def prepare(self, **kwargs):
        self.assertTrue(
            hasattr(publish, "prepare_publication"),
            "publish needs a separately audited, non-publishing candidate boundary",
        )
        return publish.prepare_publication(
            self.report, self.repo, expected_context=context(self.source), for_pr=True, **kwargs
        )

    def test_preparation_never_changes_refs_index_worktree_or_remote(self):
        refs = self.git("show-ref")
        index = (self.repo / ".git/index").read_bytes()
        files = {
            p: p.read_bytes() for p in (self.repo / "README.md", self.repo / "results/latest.json")
        }
        candidate = self.prepare()
        self.assertEqual(self.remote_head(), self.source)
        self.assertEqual(self.git("show-ref"), refs)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(
            self.git("rev-list", "--parents", "-n", "1", candidate.commit),
            f"{candidate.commit} {self.source}",
        )
        self.assertEqual(self.git("rev-parse", candidate.commit + "^{tree}"), candidate.tree)

    def test_pr_identity_is_deterministic_despite_ambient_dates(self):
        first = self.prepare()
        with patch.dict(
            os.environ,
            {
                "GIT_AUTHOR_DATE": "2030-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2031-01-01T00:00:00Z",
            },
        ):
            second = self.prepare()
        self.assertEqual(first, second)
        self.assertNotIn("[skip ci]", self.git("show", "-s", "--format=%B", first.commit))
        self.assertEqual(first.source, self.source)
        self.assertEqual(first.run_id, "12345")
        self.assertEqual(first.run_attempt, "1")
        self.assertEqual(first.branch, f"results/verified-12345-1-{self.source}")

    def test_candidate_manifest_and_bytes_match_legacy_publication(self):
        candidate = self.prepare()
        legacy = publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(candidate.tree, self.git("rev-parse", legacy + "^{tree}"))
        self.assertNotEqual(candidate.commit, legacy)
        self.assertEqual(
            len(
                self.git(
                    "diff-tree", "--no-commit-id", "--name-only", "-r", candidate.commit
                ).splitlines()
            ),
            7,
        )
        self.assertIn("[skip ci]", self.git("show", "-s", "--format=%B", legacy))

    def test_candidates_can_be_rebuilt_after_main_moves_without_publishing(self):
        first = self.prepare()
        self.git("commit", "--allow-empty", "-qm", "test: newer main")
        newer = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "origin", "HEAD:main")
        self.git("reset", "--hard", self.source)
        self.assertEqual(self.prepare(), first)
        self.assertEqual(self.remote_head(), newer)
        with self.assertRaisesRegex(BenchmarkFailure, "main advanced"):
            publish.publish(self.report, self.repo, expected_context=context(self.source))

    def test_untrusted_identity_is_verified_against_rebuilt_raw_audited_candidate(self):
        candidate = self.prepare()
        publish.verify_candidate(
            candidate, self.report, self.repo, expected_context=context(self.source)
        )
        mutations = {
            "commit": "c" * 40,
            "tree": "d" * 40,
            "source": "e" * 40,
            "source_tree": "f" * 40,
            "run_id": "12346",
            "run_attempt": "2",
            "report_sha256": "0" * 64,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaises(BenchmarkFailure):
                publish.verify_candidate(
                    replace(candidate, **{field: value}),
                    self.report,
                    self.repo,
                    expected_context=context(self.source),
                )

    def test_changed_raw_data_or_dirty_readme_invalidates_candidate(self):
        candidate = self.prepare()
        raw = next((self.repo / self.report["metadata"]["artifact_directory"]).glob("*-run-1.json"))
        original = raw.read_bytes()
        raw.write_text("{}")
        with self.assertRaises(BenchmarkFailure):
            publish.verify_candidate(
                candidate, self.report, self.repo, expected_context=context(self.source)
            )
        raw.write_bytes(original)
        (self.repo / "README.md").write_text(
            "unreviewed prefix\n" + (self.repo / "README.md").read_text()
        )
        with self.assertRaisesRegex(BenchmarkFailure, "clean source"):
            self.prepare()
        self.assertEqual(self.remote_head(), self.source)

    def test_wrong_report_context_and_source_tree_fail_before_candidate_generation(self):
        self.assertTrue(hasattr(publish, "prepare_publication"), "candidate boundary is required")
        for field, value in (("source_tree", "d" * 40), ("source_commit", "e" * 40)):
            bad = copy.deepcopy(self.report)
            bad["metadata"][field] = value
            with self.subTest(field=field), self.assertRaises(BenchmarkFailure):
                publish.prepare_publication(
                    bad, self.repo, expected_context=context(self.source), for_pr=True
                )

    def test_local_squash_reconciliation_remains_compatible_with_existing_pages(self):
        from benchmark import pages_handoff, result_pr

        candidate = self.prepare()
        squash = self.git(
            "commit-tree",
            candidate.tree,
            "-p",
            self.source,
            input=b"test: simulate an independently created squash commit\n",
        )
        repo = {"full_name": "tappe9/simple-api-benchmark", "id": 1356993741}
        pull = {
            "number": 17,
            "state": "closed",
            "merged": True,
            "draft": False,
            "commits": 1,
            "merge_commit_sha": squash,
            "head": {"sha": candidate.commit, "ref": candidate.branch, "repo": repo},
            "base": {"sha": self.source, "ref": "main", "repo": repo},
        }
        commit = {
            "sha": squash,
            "tree": {"sha": self.git("rev-parse", squash + "^{tree}")},
            "parents": [{"sha": self.git("rev-parse", squash + "^")}],
        }
        outputs = result_pr.reconcile_publication(
            candidate, pull_request=pull, merged_commit=commit
        )
        # Simulate only the already-completed Git ref update in this private temp repo.
        # This is not a GitHub API call or a server-side branch-policy test.
        self.git("push", "-q", "origin", f"{squash}:refs/heads/main")
        request = {
            "caller": "official",
            "target_sha": outputs["publication_sha"],
            "source_sha": outputs["source_sha"],
            "producer_run_id": outputs["producer_run_id"],
            "producer_run_attempt": outputs["producer_run_attempt"],
            "producer_result": "success",
        }
        event = {"repository": {"full_name": repo["full_name"], "default_branch": "main"}}
        self.assertEqual(
            pages_handoff.verify(self.repo, fixtures.context_env(self.source), event, request),
            squash,
        )
        self.assertNotEqual(squash, candidate.commit)

    def test_preparation_does_not_need_network_access(self):
        self.git("remote", "set-url", "origin", "https://invalid.example/no-network.git")
        candidate = self.prepare()
        self.assertEqual(candidate.source, self.source)

    def test_mode_is_not_coerced_from_strings_or_numbers(self):
        for value in ("true", 1, None):
            with self.subTest(value=value), self.assertRaises(BenchmarkFailure):
                publish.prepare_publication(
                    self.report, self.repo, expected_context=context(self.source), for_pr=value
                )

    def test_serialized_candidate_is_strict_and_never_treated_as_authentication(self):
        candidate = self.prepare()
        module = importlib.import_module("benchmark.publication_candidate")
        value = candidate.as_dict()
        self.assertEqual(module.PublicationCandidate.from_dict(value), candidate)
        for bad in (
            {**value, "extra": True},
            {k: v for k, v in value.items() if k != "tree"},
            {**value, "run_id": True},
            {**value, "run_attempt": "../2"},
            {**value, "commit": "HEAD"},
            {**value, "report_sha256": "a" * 40},
        ):
            with self.subTest(bad=bad), self.assertRaises(BenchmarkFailure):
                module.PublicationCandidate.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
