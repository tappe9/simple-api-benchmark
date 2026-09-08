"""Publication compatibility tests for versioned benchmark cohorts."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from registry_fixtures import expanded_report, explicit_report, extended_registry
from test_benchmark_publication import END, START, context, synthetic_report

from benchmark.results import BenchmarkFailure


class CohortPublicationTests(unittest.TestCase):
    def git(self, *args, cwd=None, **kwargs):
        return (
            subprocess.check_output(["git", *args], cwd=cwd or self.repo, **kwargs).decode().strip()
        )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Publication test")
        self.git("config", "user.email", "test@example.invalid")
        for filename in ("README.md", "README.ja.md"):
            (self.repo / filename).write_text(f"intro\n{START}\nold\n{END}\noutro\n")
        (self.repo / "source.txt").write_text("unchanged")
        (self.repo / ".gitignore").write_text(".cache/\n")
        (self.repo / "results").mkdir()
        (self.repo / "results/latest.json").write_text('{"previous":"verified bytes"}\n')
        self.git("add", ".")
        self.git("commit", "-qm", "test: initial verified state")
        self.source = self.git("rev-parse", "HEAD")
        self.git("init", "-q", "--bare", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "HEAD:main")
        self.report = synthetic_report(self.repo, source=self.source)
        self.report["metadata"]["source_tree"] = self.git("rev-parse", "HEAD^{tree}")

    def remote_head(self):
        return self.git("rev-parse", "refs/heads/main", cwd=self.remote)

    def assert_complete_transaction(self):
        from benchmark import publish

        before_index = (self.repo / ".git/index").read_bytes()
        before = (self.repo / "results/latest.json").read_bytes()
        commit = publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.remote_head(), commit)
        self.assertEqual(json.loads(self.git("show", commit + ":results/latest.json")), self.report)
        self.assertEqual(self.git("rev-parse", commit + "^"), self.source)
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        history = [path for path in changed if path.startswith("results/history/")]
        self.assertEqual(len(history), 1)
        self.assertEqual(
            set(changed), {"README.md", "README.ja.md", "results/latest.json", *history}
        )
        self.assertEqual(
            self.git("show", commit + ":results/latest.json"),
            self.git("show", commit + ":" + history[0]),
        )
        self.assertEqual((self.repo / ".git/index").read_bytes(), before_index)
        self.assertEqual((self.repo / "results/latest.json").read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)

    def test_explicit_current_cohort_uses_the_same_atomic_publication_boundary(self):
        self.report = explicit_report(self.report)
        self.assert_complete_transaction()

    def test_extended_known_cohort_must_be_complete_before_atomic_publication(self):
        from benchmark import publish
        from benchmark import registry

        self.report = expanded_report(self.report, self.repo)
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(self.source))
        with patch.object(registry, "REGISTRY", extended_registry()):
            incomplete = copy.deepcopy(self.report)
            incomplete["implementations"].pop()
            with self.assertRaises(BenchmarkFailure):
                publish.publish(incomplete, self.repo, expected_context=context(self.source))
            self.assertEqual(self.remote_head(), self.source)
            self.assert_complete_transaction()


if __name__ == "__main__":
    unittest.main()
