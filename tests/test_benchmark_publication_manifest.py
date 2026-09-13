"""Integration coverage for the exact publisher-to-Pages publication manifest."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from test_benchmark_publication import END, REPOSITORY, START, context, synthetic_report

PAGES_WORKFLOW = REPOSITORY + "/.github/workflows/pages.yml@refs/heads/main"
EXPECTED_HISTORY = "results/history/2026-09-05T11-00-00Z-12345-1.json"
EXPECTED_PATHS = {
    "README.md",
    "README.ja.md",
    "results/latest.json",
    EXPECTED_HISTORY,
    "results/charts/json-throughput.svg",
    "results/charts/postgresql-throughput.svg",
    "results/charts/cpu-throughput.svg",
}


class PublicationManifestIntegrationTests(unittest.TestCase):
    def git(self, *args: str, cwd=None) -> str:
        return subprocess.check_output(["git", *args], cwd=cwd or self.repo).decode().strip()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Publication manifest test")
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

    def test_real_publication_commit_is_authorized_by_pages(self):
        from benchmark import pages, publish

        commit = publish.publish(self.report, self.repo, expected_context=context(self.source))
        parents = self.git("rev-list", "--parents", "-n", "1", commit).split()[1:]
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        self.assertEqual(parents, [self.source])
        self.assertEqual(set(changed), EXPECTED_PATHS)

        environment = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": commit,
            "GITHUB_WORKFLOW_SHA": commit,
            "GITHUB_WORKFLOW_REF": PAGES_WORKFLOW,
            "GITHUB_EVENT_NAME": "workflow_run",
        }
        event = {
            "repository": {"full_name": REPOSITORY, "default_branch": "main"},
            "workflow_run": {
                "name": "Official benchmark",
                "path": ".github/workflows/benchmark.yml",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "head_sha": self.source,
                "head_branch": "main",
                "head_repository": {"full_name": REPOSITORY},
                "id": 12345,
                "run_attempt": 1,
            },
        }
        pages.validate_event(
            environment,
            event,
            head=commit,
            parents=parents,
            changed=changed,
            report=self.report,
        )


if __name__ == "__main__":
    unittest.main()
