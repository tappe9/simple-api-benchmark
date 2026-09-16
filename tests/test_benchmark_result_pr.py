"""Synthetic REST snapshots exercise preflight only, never GitHub writes or rules."""

import copy
import importlib
import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from benchmark.publication_candidate import PublicationCandidate
from benchmark.results import BenchmarkFailure

REPO = {"full_name": "tappe9/simple-api-benchmark", "id": 1356993741}
ACTIONS_APP = 15368
CI_WORKFLOW = 350921839


def snapshots():
    candidate = PublicationCandidate("a" * 40, "b" * 40, "c" * 40, "d" * 40, "12345", "1", "e" * 64)
    pull = {
        "number": 17,
        "state": "open",
        "merged": False,
        "draft": False,
        "commits": 1,
        "head": {"sha": candidate.commit, "ref": candidate.branch, "repo": copy.deepcopy(REPO)},
        "base": {"sha": candidate.source, "ref": "main", "repo": copy.deepcopy(REPO)},
    }
    run = {
        "id": 100,
        "run_attempt": 2,
        "check_suite_id": 200,
        "workflow_id": CI_WORKFLOW,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_sha": candidate.commit,
        "head_branch": candidate.branch,
        "repository": copy.deepcopy(REPO),
        "head_repository": copy.deepcopy(REPO),
        "status": "completed",
        "conclusion": "success",
        "pull_requests": [
            {"number": 17, "head": copy.deepcopy(pull["head"]), "base": copy.deepcopy(pull["base"])}
        ],
    }
    registry = json.loads(
        (Path(__file__).resolve().parents[1] / "benchmark/implementations.json").read_text()
    )
    names = ["plan", "shared", "smoke", "required"] + [
        f"implementation ({spec['id']})" for spec in registry["implementations"]
    ]
    jobs = [
        {
            "id": 1000 + i,
            "name": name,
            "run_id": 100,
            "run_attempt": 2,
            "head_sha": candidate.commit,
            "status": "completed",
            "conclusion": "success",
        }
        for i, name in enumerate(names)
    ]
    checks = [
        {
            "id": job["id"],
            "name": job["name"],
            "head_sha": candidate.commit,
            "check_suite": {"id": 200},
            "app": {"id": ACTIONS_APP},
            "status": "completed",
            "conclusion": "success",
        }
        for job in jobs
    ]
    rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "allowed_merge_methods": ["squash"],
                "required_approving_review_count": 0,
                "required_review_thread_resolution": True,
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": [{"context": "required", "integration_id": ACTIONS_APP}],
            },
        },
    ]
    ruleset = {
        "id": 300,
        "source_type": "Repository",
        "source": REPO["full_name"],
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": rules,
    }
    effective = [
        {
            **copy.deepcopy(rule),
            "ruleset_id": 300,
            "ruleset_source": REPO["full_name"],
            "ruleset_source_type": "Repository",
        }
        for rule in rules
    ]
    arguments = {
        "pull_request": pull,
        "candidate_commit": {
            "sha": candidate.commit,
            "tree": {"sha": candidate.tree},
            "parents": [{"sha": candidate.source}],
        },
        "ci_run": run,
        "jobs": jobs,
        "checks": checks,
        "ruleset": ruleset,
        "effective_rules": effective,
        "main_sha": candidate.source,
    }
    return candidate, arguments


def mutate(arguments, path, value):
    updated = copy.deepcopy(arguments)
    node = updated
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return updated


class ResultPRPreflightTests(unittest.TestCase):
    def setUp(self):
        self.candidate, self.arguments = snapshots()

    def module(self):
        try:
            return importlib.import_module("benchmark.result_pr")
        except ModuleNotFoundError:
            self.fail("result PRs need a fail-closed preflight separate from live writes")

    def plan(self, arguments=None):
        return self.module().plan_merge(
            self.candidate, **(self.arguments if arguments is None else arguments)
        )

    def rejects(self, path, value, code):
        module = self.module()
        with self.assertRaises(module.ResultPRFailure) as caught:
            self.plan(mutate(self.arguments, path, value))
        self.assertEqual(caught.exception.code, code)

    def test_valid_plan_is_immutable_exact_head_squash_and_not_a_write(self):
        before = copy.deepcopy(self.arguments)
        plan = self.plan()
        self.assertEqual(plan.request, {"sha": self.candidate.commit, "merge_method": "squash"})
        self.assertEqual(plan.pull_number, 17)
        self.assertEqual(plan.expected_source, self.candidate.source)
        self.assertEqual(plan.expected_tree, self.candidate.tree)
        self.assertEqual((plan.ci_run_id, plan.ci_run_attempt), (100, 2))
        self.assertEqual(self.arguments, before)
        request = plan.request
        request["sha"] = "f" * 40
        self.assertEqual(plan.request["sha"], self.candidate.commit)
        with self.assertRaises(FrozenInstanceError):
            plan.expected_source = "f" * 40

    def test_pr_identity_and_state_changes_are_rejected(self):
        mutations = [
            (("number",), True),
            (("number",), 0),
            (("state",), "closed"),
            (("merged",), True),
            (("draft",), True),
            (("commits",), 2),
            (("commits",), True),
            (("head", "sha"), "f" * 40),
            (("head", "ref"), "feature"),
            (("head", "repo", "full_name"), "attacker/fork"),
            (("head", "repo", "id"), 1),
            (("base", "sha"), "f" * 40),
            (("base", "ref"), "develop"),
            (("base", "repo", "id"), 1),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.rejects(("pull_request", *path), value, "invalid_pr")

    def test_missing_pr_identity_is_not_inferred_from_actor_label_or_green_badge(self):
        for field in self.arguments["pull_request"]:
            arguments = copy.deepcopy(self.arguments)
            del arguments["pull_request"][field]
            arguments["pull_request"].update(
                user={"login": "github-actions[bot]"}, labels=["verified"], mergeable=True
            )
            with self.subTest(field=field), self.assertRaises(BenchmarkFailure):
                self.plan(arguments)

    def test_candidate_sha_tree_and_single_measured_parent_are_required(self):
        for path, value in [
            (("sha",), "f" * 40),
            (("tree", "sha"), "f" * 40),
            (("parents",), []),
            (("parents",), [{"sha": self.candidate.source}, {"sha": "f" * 40}]),
            (("parents", 0, "sha"), "f" * 40),
        ]:
            with self.subTest(path=path):
                self.rejects(("candidate_commit", *path), value, "invalid_candidate")

    def test_stale_main_is_rejected_even_when_pr_is_mergeable(self):
        self.arguments["pull_request"]["mergeable"] = True
        self.rejects(("main_sha",), "f" * 40, "stale_main")
        self.rejects(("main_sha",), None, "stale_main")

    def test_ci_run_is_bound_to_exact_repository_workflow_pr_and_head(self):
        mutations = [
            (("id",), True),
            (("run_attempt",), 0),
            (("run_attempt",), True),
            (("check_suite_id",), 0),
            (("workflow_id",), 9),
            (("name",), "Other CI"),
            (("path",), ".github/workflows/other.yml"),
            (("event",), "push"),
            (("head_sha",), "f" * 40),
            (("head_branch",), "main"),
            (("repository", "id"), 1),
            (("head_repository", "full_name"), "attacker/fork"),
            (("pull_requests",), []),
            (("pull_requests", 0, "number"), 18),
            (("pull_requests", 0, "head", "sha"), "f" * 40),
            (("pull_requests", 0, "base", "sha"), "f" * 40),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.rejects(("ci_run", *path), value, "invalid_ci")

    def test_pending_ci_is_distinct_from_rejected_ci(self):
        module = self.module()
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            args = copy.deepcopy(self.arguments)
            args["ci_run"].update(status=status, conclusion=None)
            with self.subTest(status=status), self.assertRaises(module.ResultPRFailure) as caught:
                self.plan(args)
            self.assertEqual(caught.exception.code, "ci_pending")
        for status in ("unknown", None, True):
            self.rejects(("ci_run", "status"), status, "invalid_ci")

    def test_every_non_success_conclusion_is_rejected(self):
        for conclusion in (
            "failure",
            "cancelled",
            "skipped",
            "neutral",
            "timed_out",
            "action_required",
            "stale",
            None,
            True,
            "success ",
        ):
            for path in [
                ("ci_run", "conclusion"),
                ("jobs", 0, "conclusion"),
                ("checks", 0, "conclusion"),
            ]:
                with self.subTest(path=path, conclusion=conclusion):
                    self.rejects(path, conclusion, "ci_rejected")

    def test_all_registered_implementation_jobs_are_required_not_only_active_cohort(self):
        for field in ("jobs", "checks"):
            original = self.arguments[field]
            for index in range(len(original)):
                with self.subTest(field=field, missing=original[index]["name"]):
                    self.rejects((field,), original[:index] + original[index + 1 :], "invalid_ci")
            self.rejects((field,), original + [copy.deepcopy(original[0])], "invalid_ci")
            self.rejects(
                (field,), original + [{**original[0], "id": 9999, "name": "extra"}], "invalid_ci"
            )

    def test_job_run_attempt_head_ids_and_completion_are_bound(self):
        for field, value in [
            ("id", True),
            ("id", 0),
            ("run_id", 101),
            ("run_attempt", 1),
            ("head_sha", "f" * 40),
            ("status", "in_progress"),
        ]:
            with self.subTest(field=field):
                self.rejects(("jobs", 0, field), value, "invalid_ci")
        self.rejects(("jobs", 1, "id"), self.arguments["jobs"][0]["id"], "invalid_ci")

    def test_check_issuer_suite_head_and_job_id_must_match(self):
        for path, value in [
            (("app", "id"), 1),
            (("app",), None),
            (("check_suite", "id"), 201),
            (("head_sha",), "f" * 40),
            (("id",), 9999),
            (("status",), "queued"),
        ]:
            with self.subTest(path=path):
                self.rejects(("checks", 0, *path), value, "invalid_ci")

    def test_ruleset_must_be_active_exact_main_and_have_explicit_no_bypass(self):
        mutations = [
            (("id",), True),
            (("target",), "tag"),
            (("enforcement",), "evaluate"),
            (("source_type",), "Organization"),
            (("source",), "attacker/fork"),
            (("bypass_actors",), None),
            (
                ("bypass_actors",),
                [{"actor_id": 1, "actor_type": "Integration", "bypass_mode": "always"}],
            ),
            (("conditions", "ref_name", "include"), ["~ALL"]),
            (("conditions", "ref_name", "exclude"), ["refs/heads/main"]),
        ]
        for path, value in mutations:
            with self.subTest(path=path):
                self.rejects(("ruleset", *path), value, "policy_unverified")
        args = copy.deepcopy(self.arguments)
        del args["ruleset"]["bypass_actors"]
        with self.assertRaises(self.module().ResultPRFailure) as caught:
            self.plan(args)
        self.assertEqual(caught.exception.code, "policy_unverified")

    def test_required_check_must_be_strict_and_from_actions(self):
        for field, value in [
            ("strict_required_status_checks_policy", False),
            ("strict_required_status_checks_policy", "true"),
            ("do_not_enforce_on_create", True),
            ("required_status_checks", []),
            ("required_status_checks", [{"context": "required", "integration_id": 1}]),
            ("required_status_checks", [{"context": "other", "integration_id": ACTIONS_APP}]),
        ]:
            with self.subTest(field=field):
                self.rejects(
                    ("ruleset", "rules", 3, "parameters", field), value, "policy_unverified"
                )

    def test_pull_request_policy_preserves_single_maintainer_squash_and_resolution(self):
        for field, value in [
            ("allowed_merge_methods", ["squash", "merge"]),
            ("required_review_thread_resolution", False),
            ("required_approving_review_count", True),
            ("required_approving_review_count", 1),
            ("require_code_owner_review", True),
            ("require_last_push_approval", True),
        ]:
            with self.subTest(field=field):
                self.rejects(
                    ("ruleset", "rules", 2, "parameters", field), value, "policy_unverified"
                )

    def test_effective_rules_must_prove_exact_policy_and_not_just_listed_inactive_config(self):
        rules = self.arguments["effective_rules"]
        for index in range(len(rules)):
            self.rejects(
                ("effective_rules",), rules[:index] + rules[index + 1 :], "policy_unverified"
            )
        for field, value in [
            ("ruleset_id", 301),
            ("ruleset_source", "attacker/fork"),
            ("ruleset_source_type", "Organization"),
        ]:
            self.rejects(("effective_rules", 0, field), value, "policy_unverified")
        self.rejects(
            ("effective_rules", 3, "parameters", "strict_required_status_checks_policy"),
            False,
            "policy_unverified",
        )
        self.rejects(("effective_rules",), rules + [copy.deepcopy(rules[0])], "policy_unverified")
        self.rejects(
            ("ruleset", "rules"), self.arguments["ruleset"]["rules"][:3], "policy_unverified"
        )

    def test_effective_rule_json_types_cannot_masquerade_as_policy_values(self):
        self.rejects(
            ("effective_rules", 2, "parameters", "required_approving_review_count"),
            False,
            "policy_unverified",
        )
        self.rejects(
            ("effective_rules", 3, "parameters", "strict_required_status_checks_policy"),
            1,
            "policy_unverified",
        )

    def test_inactive_registered_members_remain_required(self):
        from benchmark import registry

        data = copy.deepcopy(registry.REGISTRY)
        data["active_cohort"] = "four-stack-v1"
        with patch.object(registry, "REGISTRY", data):
            self.plan()
            jobs = self.arguments["jobs"]
            self.rejects(
                ("jobs",),
                [job for job in jobs if job["name"] != "implementation (rust-axum)"],
                "invalid_ci",
            )

    def test_unsupported_ci_language_fails_with_classified_error(self):
        from benchmark import registry

        data = copy.deepcopy(registry.REGISTRY)
        data["implementations"][0]["language"] = "Unconfigured language"
        with patch.object(registry, "REGISTRY", data):
            with self.assertRaises(self.module().ResultPRFailure) as caught:
                self.plan()
        self.assertEqual(caught.exception.code, "invalid_ci")

    def test_malformed_nested_snapshots_fail_with_classified_errors(self):
        for field in (
            "pull_request",
            "candidate_commit",
            "ci_run",
            "jobs",
            "checks",
            "ruleset",
            "effective_rules",
        ):
            for value in (None, True, "untrusted", [None], {"unexpected": True}):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(self.module().ResultPRFailure),
                ):
                    self.plan({**self.arguments, field: value})


class ResultPRReconciliationTests(unittest.TestCase):
    module = ResultPRPreflightTests.module

    def setUp(self):
        self.candidate, args = snapshots()
        self.pull = args["pull_request"]
        self.merged_sha = "f" * 40
        self.pull.update(state="closed", merged=True, merge_commit_sha=self.merged_sha)
        self.commit = {
            "sha": self.merged_sha,
            "tree": {"sha": self.candidate.tree},
            "parents": [{"sha": self.candidate.source}],
        }

    def reconcile(self):
        module = self.module()
        self.assertTrue(
            hasattr(module, "reconcile_publication"),
            "lost responses need read-only merged-identity reconciliation",
        )
        return module.reconcile_publication(
            self.candidate, pull_request=self.pull, merged_commit=self.commit
        )

    def test_actual_squash_sha_and_original_producer_attempt_are_emitted(self):
        expected = {
            "publication_sha": self.merged_sha,
            "source_sha": self.candidate.source,
            "producer_run_id": "12345",
            "producer_run_attempt": "1",
        }
        self.assertEqual(self.reconcile(), expected)
        self.assertEqual(self.reconcile(), expected)
        self.assertNotEqual(expected["publication_sha"], self.candidate.commit)

    def test_read_only_reconciliation_does_not_change_supplied_evidence(self):
        original = copy.deepcopy((self.pull, self.commit))
        self.reconcile()
        self.assertEqual((self.pull, self.commit), original)

    def test_open_or_closed_unmerged_pr_never_means_success(self):
        for state, merged in (("open", False), ("closed", False), ("closed", None), ("closed", 1)):
            self.pull.update(state=state, merged=merged)
            with self.subTest(state=state, merged=merged), self.assertRaises(BenchmarkFailure):
                self.reconcile()

    def test_incorrect_parent_tree_or_returned_merge_sha_never_emits_outputs(self):
        original = copy.deepcopy(self.commit)
        for update in (
            {"sha": "0" * 40},
            {"tree": {"sha": "0" * 40}},
            {"parents": []},
            {"parents": [{"sha": "0" * 40}]},
            {"parents": [{"sha": self.candidate.source}, {"sha": self.candidate.commit}]},
        ):
            self.commit = {**copy.deepcopy(original), **update}
            with self.subTest(update=update), self.assertRaises(BenchmarkFailure):
                self.reconcile()

    def test_invalid_merge_sha_and_missing_or_malformed_evidence_fail_closed(self):
        for sha in (None, "HEAD", "f" * 39, True):
            self.pull["merge_commit_sha"] = sha
            with self.subTest(sha=sha), self.assertRaises(BenchmarkFailure):
                self.reconcile()
        self.pull["merge_commit_sha"] = self.merged_sha
        self.commit = None
        with self.assertRaises(BenchmarkFailure):
            self.reconcile()

    def test_candidate_head_change_still_invalidates_reconciliation(self):
        self.pull["head"]["sha"] = "0" * 40
        with self.assertRaises(BenchmarkFailure):
            self.reconcile()

    def test_main_advancement_after_valid_merge_does_not_relabel_publication(self):
        # GitHub can return a later base SHA. The actual commit's parent, not the
        # mutable PR base or current main, establishes the measured-source parent.
        self.pull["base"]["sha"] = "0" * 40
        self.assertEqual(self.reconcile()["publication_sha"], self.merged_sha)


if __name__ == "__main__":
    unittest.main()
