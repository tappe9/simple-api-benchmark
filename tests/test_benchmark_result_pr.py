"""Synthetic publication transactions use isolated real Git repositories only."""

import copy
import importlib
import unittest

import test_benchmark_publication_manifest as manifest
from test_benchmark_publication import context

from benchmark.results import BenchmarkFailure


class CandidateTests(unittest.TestCase):
    setUp = manifest.PublicationManifestIntegrationTests.setUp
    git = manifest.PublicationManifestIntegrationTests.git

    def prepare(self, report=None):
        module = importlib.import_module("benchmark.publish")
        self.assertTrue(hasattr(module, "prepare_candidate"), "separate audited candidate required")
        return module.prepare_candidate(
            report or self.report, self.repo, expected_context=context(self.source)
        )

    def test_candidate_is_deterministic_without_publishing_or_skipping_ci(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first, second)
        self.assertEqual(first.source, self.source)
        self.assertEqual(first.source_tree, self.report["metadata"]["source_tree"])
        self.assertEqual(self.git("rev-parse", first.sha + "^{tree}"), first.tree)
        self.assertEqual(
            self.git("rev-list", "--parents", "-1", first.sha).split(), [first.sha, self.source]
        )
        self.assertEqual(
            set(
                self.git("diff-tree", "--no-commit-id", "--name-only", "-r", first.sha).splitlines()
            ),
            manifest.EXPECTED_PATHS,
        )
        self.assertNotIn("[skip ci]", self.git("show", "-s", "--format=%B", first.sha))
        self.assertEqual(self.git("rev-parse", "refs/heads/main", cwd=self.remote), self.source)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual((first.run_id, first.run_attempt), ("12345", "1"))

    def test_candidate_rejects_source_mismatch_and_dirty_checkout(self):
        bad = copy.deepcopy(self.report)
        bad["metadata"]["source_tree"] = "f" * 40
        with self.assertRaises(BenchmarkFailure):
            self.prepare(bad)
        (self.repo / "source.txt").write_text("unaudited change")
        with self.assertRaises(BenchmarkFailure):
            self.prepare()

    def test_candidate_reaudits_raw_evidence(self):
        artifact = self.repo / self.report["metadata"]["artifact_directory"]
        next(artifact.glob("*-run-1.json")).write_text("{}")
        with self.assertRaises(BenchmarkFailure):
            self.prepare()

    def test_candidate_does_not_depend_on_transport_and_legacy_still_rejects_stale_main(self):
        first = self.prepare()
        self.git("push", "-q", "origin", first.sha + ":refs/heads/main")
        self.assertEqual(self.prepare(), first)
        from benchmark.publish import publish

        with self.assertRaisesRegex(BenchmarkFailure, "main advanced"):
            publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.git("rev-parse", "refs/heads/main", cwd=self.remote), first.sha)


if __name__ == "__main__":
    unittest.main()
