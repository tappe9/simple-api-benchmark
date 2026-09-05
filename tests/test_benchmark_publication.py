"""Publication tests use synthetic data and temporary Git repositories, never official results."""

import copy
import importlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.environment import pinned_versions
from benchmark.results import BenchmarkFailure, parse_oha, select_run
from benchmark.run import IMPLEMENTATIONS, PROFILE

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40
TREE = "b" * 40
REPOSITORY = "tappe9/simple-api-benchmark"
WORKFLOW = REPOSITORY + "/.github/workflows/benchmark.yml@refs/heads/main"
START = "<!-- benchmark-results:start -->"
END = "<!-- benchmark-results:end -->"


def context_env(source=SOURCE):
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": source,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_WORKFLOW_REF": WORKFLOW,
        "GITHUB_WORKFLOW_SHA": source,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
    }


def context(source=SOURCE):
    return {
        "repository": REPOSITORY,
        "ref": "refs/heads/main",
        "source_commit": source,
        "event": "workflow_dispatch",
        "workflow_ref": WORKFLOW,
        "workflow_sha": source,
        "run_id": "12345",
        "run_attempt": "1",
        "run_url": "https://github.com/" + REPOSITORY + "/actions/runs/12345",
    }


def synthetic_report(root, *, source=SOURCE):
    """Create explicitly synthetic full-shaped data for isolated negative/transaction tests."""
    artifact = root / ".cache/official/raw/sab-benchmark-test"
    artifact.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "status": "verified",
        "mode": "official",
        "official": True,
        "started_at": "2026-09-05T10:00:00+00:00",
        "completed_at": "2026-09-05T11:00:00+00:00",
        "conditions": copy.deepcopy(PROFILE),
        "metadata": {
            "source_commit": source,
            "source_tree": TREE,
            "artifact_directory": str(artifact.relative_to(root)),
            "versions": pinned_versions(),
            "github": context(source),
            "runner": {
                "name": "synthetic-test-runner", "environment": "github-hosted",
                "os": "Linux", "architecture": "X64", "image_os": "ubuntu24",
                "image_version": "synthetic", "cpu_model": "synthetic CPU",
            },
            "docker": {"ServerVersion": "synthetic"},
            "docker_cli": "synthetic", "docker_compose": "synthetic",
        },
        "implementations": [],
    }
    raw = json.loads((ROOT / "tests/fixtures/oha-1.16.0/timed.json").read_text())
    raw["summary"]["total"] = 30.5
    count = raw["statusCodeDistribution"]["200"]
    raw["summary"]["requestsPerSec"] = count / 30.5
    raw["summary"]["sizePerSec"] = raw["summary"]["totalData"] / 30.5
    raw["metrics"]["requests_per_sec"] = count / 30.5
    for implementation in IMPLEMENTATIONS:
        backend = {
            "implementation": implementation, "contract_checks": 14,
            "container": {"id": "c" * 64, "image_id": "sha256:" + "d" * 64,
                          "command": ["synthetic"], "postgresql_version": "PostgreSQL synthetic"},
            "endpoints": [],
        }
        for endpoint in PROFILE["endpoints"]:
            runs = []
            stem = implementation + "-" + endpoint.strip("/").replace("/", "-")
            for index in (1, 2, 3):
                path = artifact / f"{stem}-run-{index}.json"
                path.write_text(json.dumps(raw))
                sample = {"at": "2026-09-05T10:30:00+00:00", "bytes": index * 1048576,
                          "container_id": backend["container"]["id"]}
                path.with_suffix(".memory.jsonl").write_text(json.dumps(sample) + "\n")
                run = parse_oha(path.read_bytes(), duration=30)
                run.update(run=index, peak_memory_bytes=sample["bytes"], memory_samples=1)
                runs.append(run)
            backend["endpoints"].append({"endpoint": endpoint, "runs": runs,
                                         "selected": select_run(runs)})
        report["implementations"].append(backend)
    return report


class ModuleTest(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module("benchmark." + name)
        except ModuleNotFoundError:
            self.fail(f"benchmark.{name} must implement the tested publication boundary")


class TrustedContextTests(ModuleTest):
    def test_only_expected_trusted_main_events_are_accepted(self):
        official = self.module("official")
        for event in ("schedule", "workflow_dispatch"):
            env = {**context_env(), "GITHUB_EVENT_NAME": event}
            self.assertEqual(official.trusted_context(env)["event"], event)
        changes = {
            "GITHUB_ACTIONS": "false", "GITHUB_REPOSITORY": "attacker/fork",
            "GITHUB_REF": "refs/heads/feature", "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_WORKFLOW_REF": WORKFLOW.replace("main", "feature"),
            "GITHUB_WORKFLOW_SHA": "b" * 40, "GITHUB_SHA": "fixture",
            "GITHUB_RUN_ID": "../1", "GITHUB_RUN_ATTEMPT": "0",
        }
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                official.trusted_context({**context_env(), key: value})
        for key in context_env():
            env = context_env()
            del env[key]
            with self.subTest(missing=key), self.assertRaises(BenchmarkFailure):
                official.trusted_context(env)

    def test_rejected_context_cannot_start_benchmark(self):
        official = self.module("official")
        with patch.dict(os.environ, {}, clear=True), patch.object(official, "run_benchmark") as run:
            self.assertEqual(official.main(), 1)
            run.assert_not_called()


class ReportTests(ModuleTest):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = synthetic_report(self.root)

    def test_all_36_normalized_records_match_raw_and_selected_metrics(self):
        report = self.module("report")
        report.validate_report(self.report)
        report.audit_raw(self.report, self.root)

    def test_local_smoke_partial_invalid_and_foreign_reports_are_rejected(self):
        report = self.module("report")
        def change(path, value):
            bad = copy.deepcopy(self.report)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return bad
        mutations = [
            (("official",), False), (("official",), 1), (("mode",), "smoke"),
            (("status",), "failed"), (("schema_version",), True),
            (("conditions", "duration_seconds"), 2), (("conditions", "workers"), True),
            (("implementations",), self.report["implementations"][:3]),
            (("implementations", 0, "contract_checks"), 0),
            (("implementations", 0, "endpoints", 0, "runs"), []),
            (("implementations", 0, "endpoints", 0, "selected", "peak_memory_bytes"), 123),
            (("metadata", "versions"), {}), (("metadata", "source_commit"), "fixture"),
            (("metadata", "github", "ref"), "refs/pull/1/merge"),
            (("metadata", "runner", "environment"), "self-hosted"),
            (("metadata", "docker"), {}), (("completed_at",), "2026-09-04T11:00:00Z"),
        ]
        for path, value in mutations:
            with self.subTest(path=path), self.assertRaises(BenchmarkFailure):
                report.validate_report(change(path, value))
        with self.assertRaises(BenchmarkFailure):
            report.validate_report(self.report, expected_context={**context(), "run_id": "12346"})

    def test_raw_tampering_missing_wrong_container_and_symlink_fail(self):
        report = self.module("report")
        path = next((self.root / self.report["metadata"]["artifact_directory"]).glob("*-run-1.json"))
        original = path.read_bytes()
        path.write_text("{}")
        with self.assertRaises(BenchmarkFailure):
            report.audit_raw(self.report, self.root)
        path.unlink()
        with self.assertRaises((BenchmarkFailure, OSError)):
            report.audit_raw(self.report, self.root)
        outside = self.root / "outside.json"
        outside.write_bytes(original)
        path.symlink_to(outside)
        with self.assertRaises(BenchmarkFailure):
            report.audit_raw(self.report, self.root)
        path.unlink()
        path.write_bytes(original)
        memory = path.with_suffix(".memory.jsonl")
        sample = json.loads(memory.read_text())
        sample["container_id"] = "e" * 64
        memory.write_text(json.dumps(sample) + "\n")
        with self.assertRaises(BenchmarkFailure):
            report.audit_raw(self.report, self.root)

    def test_artifact_path_cannot_escape_expected_raw_directory(self):
        report = self.module("report")
        for value in ("/tmp", "../../escape", ".cache/official/raw/../../other"):
            bad = copy.deepcopy(self.report)
            bad["metadata"]["artifact_directory"] = value
            with self.subTest(value=value), self.assertRaises(BenchmarkFailure):
                report.audit_raw(bad, self.root)


class ReadmeTests(ModuleTest):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.report = synthetic_report(Path(temporary.name))

    def test_same_selected_data_is_rendered_in_both_languages_without_other_changes(self):
        generator = self.module("generate_readme")
        source = f"intro\n{START}\nold\n{END}\noutro\n"
        for locale in ("en", "ja"):
            text = generator.replace_section(source, generator.render(self.report, locale))
            self.assertTrue(text.startswith("intro\n" + START))
            self.assertTrue(text.endswith(END + "\noutro\n"))
            self.assertNotIn("old", text)
            self.assertIn(self.report["completed_at"], text)
            self.assertIn(SOURCE, text)
            self.assertIn(context()["run_url"], text)
            self.assertEqual(text.count("| Go / Gin |"), 3)
            self.assertIn("2.000", text)  # selected run's memory, not maximum of all 3 runs
            self.assertNotIn("3.000", text)
            for endpoint in self.report["implementations"][0]["endpoints"]:
                self.assertIn(f'{endpoint["selected"]["requests_per_second"]:,.3f}', text)
            self.assertEqual(generator.replace_section(text, generator.render(self.report, locale)), text)

    def test_empty_state_is_honest_and_bad_markers_fail_closed(self):
        generator = self.module("generate_readme")
        self.assertIn("No verified official", generator.render(None, "en"))
        self.assertIn("公式", generator.render(None, "ja"))
        self.assertNotIn("0.000", generator.render(None, "en"))
        for source in ("no markers", START, END + START, START + START + END, START + END + END):
            with self.subTest(source=source), self.assertRaises(BenchmarkFailure):
                generator.replace_section(source, "replacement")
        self.report["official"] = False
        with self.assertRaises(BenchmarkFailure):
            generator.render(self.report, "en")


class GitPublicationTests(ModuleTest):
    def git(self, *args, cwd=None, **kwargs):
        return subprocess.check_output(["git", *args], cwd=cwd or self.repo, **kwargs).decode().strip()

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

    def test_one_commit_contains_both_readmes_latest_and_identical_history(self):
        publish = self.module("publish")
        before_index = (self.repo / ".git/index").read_bytes()
        before = (self.repo / "results/latest.json").read_bytes()
        commit = publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.remote_head(), commit)
        self.assertEqual(self.git("rev-parse", commit + "^"), self.source)
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        history = [p for p in changed if p.startswith("results/history/")]
        self.assertEqual(len(history), 1)
        self.assertEqual(set(changed), {"README.md", "README.ja.md", "results/latest.json", *history})
        self.assertEqual(self.git("show", commit + ":results/latest.json"), self.git("show", commit + ":" + history[0]))
        self.assertEqual((self.repo / ".git/index").read_bytes(), before_index)
        self.assertEqual((self.repo / "results/latest.json").read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)

    def test_failures_before_commit_and_rejected_push_preserve_remote_and_worktree(self):
        publish = self.module("publish")
        before = (self.repo / "results/latest.json").read_bytes()
        bad = copy.deepcopy(self.report)
        bad["implementations"].pop()
        with self.assertRaises(BenchmarkFailure):
            publish.publish(bad, self.repo, expected_context=context(self.source))
        (self.repo / "README.ja.md").write_text("missing markers")
        self.git("add", "README.ja.md")  # dirty tree must also fail, never stage user work
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.git("reset", "--hard", "HEAD")
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.remote_head(), self.source)
        self.assertEqual((self.repo / "results/latest.json").read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_concurrent_main_update_is_never_overwritten(self):
        publish = self.module("publish")
        self.git("commit", "--allow-empty", "-qm", "test: concurrent change")
        newer = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "origin", "HEAD:main")
        self.git("reset", "--hard", self.source)
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.assertEqual(self.remote_head(), newer)

    def test_history_collision_is_not_overwritten(self):
        publish = self.module("publish")
        filename = publish.history_path(self.report)
        path = self.repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("previous history")
        self.git("add", str(path))
        self.git("commit", "-qm", "test: existing history")
        self.git("push", "-q", "origin", "HEAD:main")
        source = self.git("rev-parse", "HEAD")
        self.report["metadata"].update(source_commit=source, source_tree=self.git("rev-parse", "HEAD^{tree}"), github=context(source))
        with self.assertRaises(BenchmarkFailure):
            publish.publish(self.report, self.repo, expected_context=context(source))
        self.assertEqual(self.remote_head(), source)
        self.assertEqual(path.read_text(), "previous history")


if __name__ == "__main__":
    unittest.main()
