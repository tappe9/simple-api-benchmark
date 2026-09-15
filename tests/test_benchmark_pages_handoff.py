"""Verify reusable Pages callers against real isolated Git publications."""

import copy
import importlib
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import test_benchmark_publication as publication_cases
from test_benchmark_publication import context, context_env

from benchmark import publish
from benchmark.results import BenchmarkFailure


class HandoffTests(unittest.TestCase):
    # Reuse only the fixture/utility methods, not another TestCase's test methods.
    setUp = publication_cases.GitPublicationTests.setUp
    git = publication_cases.GitPublicationTests.git
    remote_head = publication_cases.GitPublicationTests.remote_head

    def module(self):
        try:
            return importlib.import_module("benchmark.pages_handoff")
        except ModuleNotFoundError:
            self.fail("reusable Pages needs an explicit caller/publication authorization boundary")

    def official(self):
        self.commit = publish.publish(self.report, self.repo, expected_context=context(self.source))
        self.environment = context_env(self.source)
        self.event = {
            "repository": {"full_name": "tappe9/simple-api-benchmark", "default_branch": "main"}
        }
        self.request = {
            "caller": "official",
            "target_sha": self.commit,
            "source_sha": self.source,
            "producer_run_id": "12345",
            "producer_run_attempt": "1",
            "producer_result": "success",
        }

    def verify(self):
        return self.module().verify(self.repo, self.environment, self.event, self.request)

    def test_actual_publication_is_accepted_without_spoofing_github_context(self):
        self.official()
        before = copy.deepcopy(self.environment)
        self.assertEqual(self.verify(), self.commit)
        self.assertEqual(self.environment, before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_scheduled_and_bot_or_maintainer_dispatch_use_the_same_validation(self):
        self.official()
        for actor in ("tappe9", "github-actions[bot]"):
            self.environment["GITHUB_ACTOR"] = actor
            with self.subTest(actor=actor):
                self.assertEqual(self.verify(), self.commit)
        # A scheduled report must retain its actual event, not claim dispatch provenance.
        self.environment["GITHUB_EVENT_NAME"] = "schedule"
        with self.assertRaises(BenchmarkFailure):
            self.verify()
        self.git("update-ref", "refs/heads/main", self.source, cwd=self.remote)
        self.report["metadata"]["github"]["event"] = "schedule"
        self.commit = publish.publish(
            self.report, self.repo, expected_context={**context(self.source), "event": "schedule"}
        )
        self.request["target_sha"] = self.commit
        self.assertEqual(self.verify(), self.commit)

    def test_deployment_only_retry_keeps_original_producer_attempt(self):
        self.official()
        self.environment["GITHUB_RUN_ATTEMPT"] = "2"
        self.assertEqual(self.verify(), self.commit)
        self.request["producer_run_attempt"] = "2"
        with self.assertRaises(BenchmarkFailure):
            self.verify()
        self.request["producer_run_attempt"] = "3"
        with self.assertRaises(BenchmarkFailure):
            self.verify()

    def test_missing_forged_and_failed_producer_outputs_fail_closed(self):
        self.official()
        original = self.request.copy()
        for key in original:
            self.request = {k: v for k, v in original.items() if k != key}
            with self.subTest(missing=key), self.assertRaises(BenchmarkFailure):
                self.verify()
        for key, values in {
            "caller": ["", "unknown", "pages"],
            "target_sha": ["", "main", "-o", "f" * 40, "a" * 40 + "\ninjected=1"],
            "source_sha": ["", "f" * 40],
            "producer_run_id": ["0", "99999", "12345\nextra=x"],
            "producer_run_attempt": ["0", "01", "2"],
            "producer_result": ["failure", "cancelled", "skipped", "", "success "],
        }.items():
            for value in values:
                self.request = {**original, key: value}
                with self.subTest(key=key, value=value), self.assertRaises(BenchmarkFailure):
                    self.verify()

    def test_untrusted_caller_ref_workflow_and_repository_are_rejected(self):
        self.official()
        original = self.environment.copy()
        for key, value in {
            "GITHUB_ACTIONS": "false",
            "GITHUB_REF": "refs/heads/feature",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_WORKFLOW_REF": "tappe9/simple-api-benchmark/.github/workflows/ci.yml@refs/heads/main",
            "GITHUB_WORKFLOW_SHA": "a" * 40,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "9876",
            "GITHUB_REPOSITORY": "other/fork",
        }.items():
            self.environment = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                self.verify()
        self.environment = original
        for repository in (None, [], {}, {"full_name": "other/fork", "default_branch": "main"}):
            self.event["repository"] = repository
            with self.subTest(repository=repository), self.assertRaises(BenchmarkFailure):
                self.verify()

    def test_current_main_is_rechecked_and_stale_publication_is_not_deployed(self):
        self.official()
        self.verify()
        # Advance the isolated remote after a successful build-time verification.
        self.git("checkout", "-q", "--detach", self.commit)
        self.git("commit", "--allow-empty", "-qm", "test: newer main")
        self.git("push", "-q", "origin", "HEAD:main")
        self.git("checkout", "-q", "--detach", self.source)
        with self.assertRaisesRegex(BenchmarkFailure, "main advanced"):
            self.verify()

    def test_tampered_manifest_or_content_cannot_pass_as_a_publication(self):
        self.official()
        self.git("checkout", "-q", "--detach", self.commit)
        chart = self.repo / "results/charts/json-throughput.svg"
        chart.write_text("forged chart")
        self.git("add", ".")
        self.git("commit", "--amend", "--no-edit", "-q")
        forged = self.git("rev-parse", "HEAD")
        self.git("fetch", "-q", str(self.repo), forged, cwd=self.remote)
        self.git("update-ref", "refs/heads/main", forged, cwd=self.remote)
        self.git("checkout", "-q", "--detach", self.source)
        self.request["target_sha"] = forged
        with self.assertRaisesRegex(BenchmarkFailure, "content"):
            self.verify()

    def test_regular_pages_caller_accepts_main_ci_and_explicit_recovery_only(self):
        self.environment = context_env(self.source)
        self.environment["GITHUB_WORKFLOW_REF"] = (
            "tappe9/simple-api-benchmark/.github/workflows/pages.yml@refs/heads/main"
        )
        self.event = {
            "repository": {"full_name": "tappe9/simple-api-benchmark", "default_branch": "main"}
        }
        self.request = dict(
            caller="pages",
            target_sha=self.source,
            source_sha="",
            producer_run_id="",
            producer_run_attempt="",
            producer_result="",
        )
        self.assertEqual(self.verify(), self.source)
        self.environment["GITHUB_EVENT_NAME"] = "workflow_run"
        self.event["workflow_run"] = dict(
            name="CI",
            path=".github/workflows/ci.yml",
            event="push",
            status="completed",
            conclusion="success",
            head_sha=self.source,
            head_branch="main",
            head_repository=self.event["repository"],
        )
        self.assertEqual(self.verify(), self.source)
        for key, value in (
            ("conclusion", "skipped"),
            ("conclusion", "failure"),
            ("name", "Official benchmark"),
            ("event", "pull_request"),
        ):
            original = self.event["workflow_run"].copy()
            self.event["workflow_run"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(BenchmarkFailure):
                self.verify()
            self.event["workflow_run"] = original
        self.request["producer_result"] = "success"
        with self.assertRaises(BenchmarkFailure):
            self.verify()

    def test_build_uses_verified_target_and_returns_attempt_bound_artifact_name(self):
        self.official()
        # The build's external site generator is isolated; the authorization uses real Git.
        output = self.root / "output"
        output.touch()
        with patch.object(
            self.module(), "build_site", return_value=self.repo / ".cache/site"
        ) as builder:
            self.module().prepare(self.repo, self.environment, self.event, self.request, output)
        target_root = builder.call_args.args[0]
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=target_root), self.commit)
        self.assertEqual(
            (target_root / "results/latest.json").read_bytes(),
            self.git_bytes(self.commit, "results/latest.json"),
        )
        self.assertIn(f"artifact_name=github-pages-{self.commit}-12345-1\n", output.read_text())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)

    def git_bytes(self, commit, path):
        import subprocess

        return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=self.repo)

    def test_publication_outputs_appear_only_after_successful_push(self):
        self.official()
        # Exercise the real publisher CLI transaction on a fresh isolated remote.
        self.git("update-ref", "refs/heads/main", self.source, cwd=self.remote)
        selected = self.repo / ".cache/official/selected.json"
        selected.write_text(json.dumps(self.report))
        output = self.root / "outputs"
        output.touch()
        original_git = publish.git

        def local_git(root, *args, **kwargs):
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/tappe9/simple-api-benchmark"
            return original_git(root, *args, **kwargs)

        env = {
            **os.environ,
            **context_env(self.source),
            "GH_TOKEN": "synthetic-test-only",
            "GITHUB_OUTPUT": str(output),
        }
        with (
            patch.object(publish, "ROOT", self.repo),
            patch.object(publish, "git", side_effect=local_git),
            patch.dict(os.environ, env, clear=True),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(publish.main(), 0)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(
            outputs,
            dict(
                publication_sha=self.remote_head(),
                source_sha=self.source,
                producer_run_id="12345",
                producer_run_attempt="1",
            ),
        )
        output.write_text("")
        with (
            patch.object(publish, "ROOT", self.repo),
            patch.object(publish, "git", side_effect=local_git),
            patch.dict(os.environ, env, clear=True),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(publish.main(), 1)
        self.assertEqual(output.read_bytes(), b"")

    def test_parent_manifest_tree_history_and_regular_file_constraints(self):
        from benchmark.publication import history_path

        for mutation, message in (
            ("manifest", "manifest mismatch"),
            ("source_tree", "source tree mismatch"),
            ("history", "history content mismatch"),
            ("symlink", "invalid publication file"),
            ("parent", "parent mismatch"),
        ):
            # Each case owns a separate repository, including its shallow boundary.
            self.setUp()
            self.official()
            original = self.commit
            self.git("checkout", "-q", "--detach", original)
            if mutation == "parent":
                self.git("commit", "--allow-empty", "-qm", "test: unrelated parent")
            else:
                if mutation == "manifest":
                    (self.repo / "unexpected.txt").write_text("not a result")
                elif mutation == "source_tree":
                    path = self.repo / "results/latest.json"
                    report = json.loads(path.read_bytes())
                    report["metadata"]["source_tree"] = "f" * 40
                    path.write_text(json.dumps(report))
                elif mutation == "history":
                    (self.repo / history_path(self.report)).write_text("forged")
                else:
                    path = self.repo / "results/charts/json-throughput.svg"
                    path.unlink()
                    path.symlink_to("../../README.md")
                self.git("add", ".")
                self.git("commit", "--amend", "--no-edit", "-q")
            forged = self.git("rev-parse", "HEAD")
            self.git("fetch", "-q", str(self.repo), forged, cwd=self.remote)
            self.git("update-ref", "refs/heads/main", forged, cwd=self.remote)
            self.git("checkout", "-q", "--detach", self.source)
            self.request["target_sha"] = forged
            with self.subTest(mutation=mutation), self.assertRaisesRegex(BenchmarkFailure, message):
                self.verify()

    def test_real_site_build_preserves_report_and_uses_trusted_assets(self):
        import shutil
        from pathlib import Path

        source_root = Path(__file__).resolve().parents[1]
        shutil.copytree(source_root / "site", self.repo / "site")
        self.git("add", "site")
        self.git("commit", "-qm", "test: add trusted site assets")
        self.git("push", "-q", "origin", "HEAD:main")
        self.source = self.git("rev-parse", "HEAD")
        self.report["metadata"].update(
            source_commit=self.source,
            source_tree=self.git("rev-parse", "HEAD^{tree}"),
            github=context(self.source),
        )
        self.official()
        output = self.root / "build-output"
        output.touch()
        built = self.module().prepare(self.repo, self.environment, self.event, self.request, output)
        self.assertEqual(
            (built / "results/latest.json").read_bytes(),
            self.git_bytes(self.commit, "results/latest.json"),
        )
        self.assertEqual(
            (built / "app.mjs").read_bytes(), (source_root / "site/app.mjs").read_bytes()
        )
        self.assertEqual(
            len(json.loads((built / "results/history/index.json").read_bytes())["runs"]), 1
        )

    def test_cli_checks_context_and_remote_without_a_write_credential(self):
        self.official()
        module = self.module()
        event_path = self.root / "event.json"
        event_path.write_text(json.dumps(self.event))
        env = {
            **os.environ,
            **self.environment,
            "GITHUB_EVENT_PATH": str(event_path),
            **{"PAGES_" + key.upper(): value for key, value in self.request.items()},
        }
        env.pop("GH_TOKEN", None)
        original = module.git_text

        def local_git(root, *args):
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/tappe9/simple-api-benchmark"
            return original(root, *args)

        with (
            patch.object(module, "ROOT", self.repo),
            patch.object(module, "git_text", side_effect=local_git),
            patch.dict(os.environ, env, clear=True),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(module.main(["verify"]), 0)
            os.environ["PAGES_PRODUCER_RESULT"] = "skipped"
            self.assertEqual(module.main(["verify"]), 1)
        with (
            patch.object(module, "ROOT", self.repo),
            patch.dict(os.environ, env, clear=True),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                module.main(["verify"]), 1
            )  # Non-repository origin is not allowed by the CLI.

    def test_no_outputs_when_upload_target_is_invalid_or_push_is_rejected(self):
        selected = self.repo / ".cache/official/selected.json"
        selected.write_text(json.dumps(self.report))
        output = self.root / "outputs"
        original = publish.git

        def local_git(root, *args, **kwargs):
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/tappe9/simple-api-benchmark"
            return original(root, *args, **kwargs)

        env = {
            **os.environ,
            **context_env(self.source),
            "GH_TOKEN": "test-only",
            "GITHUB_OUTPUT": str(output),
        }
        with (
            patch.object(publish, "ROOT", self.repo),
            patch.object(publish, "git", side_effect=local_git),
            patch.dict(os.environ, env, clear=True),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(publish.main(), 1)
            self.assertEqual(self.remote_head(), self.source)
            output.touch()
            hook = self.remote / "hooks/pre-receive"
            hook.write_text("#!/bin/sh\nexit 1\n")
            hook.chmod(0o755)
            self.assertEqual(publish.main(), 1)
            self.assertEqual(output.read_bytes(), b"")
            self.assertEqual(self.remote_head(), self.source)


if __name__ == "__main__":
    unittest.main()
