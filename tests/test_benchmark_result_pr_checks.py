"""Gate mutations are synthetic; they never grant real publication permission."""

import copy
import importlib
import unittest

from benchmark.publish import Candidate
from benchmark.registry import load_registry
from benchmark.results import BenchmarkFailure

REPO = "tappe9/simple-api-benchmark"
CANDIDATE = Candidate("a" * 40, "b" * 40, "c" * 40, "d" * 40, "12345", "1")


def pull_request(candidate=CANDIDATE):
    return {
        "number": 63,
        "state": "open",
        "merged": False,
        "draft": False,
        "head": {"sha": candidate.sha, "ref": candidate.branch, "repo": {"full_name": REPO}},
        "base": {"sha": candidate.source, "ref": "main", "repo": {"full_name": REPO}},
        "commits": 1,
        "changed_files": 7,
        "mergeable": True,
        "mergeable_state": "clean",
    }


def ci_evidence(candidate=CANDIDATE):
    run = {
        "id": 900,
        "run_attempt": 1,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_sha": candidate.sha,
        "head_branch": candidate.branch,
        "check_suite_id": 800,
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "pull_requests": [pull_request(candidate)],
    }
    names = ["plan", "shared", "smoke", "required"] + [
        "implementation (" + spec["id"] + ")" for spec in load_registry()["implementations"]
    ]
    jobs = [
        {
            "id": 1000 + i,
            "name": name,
            "run_id": 900,
            "run_attempt": 1,
            "head_sha": candidate.sha,
            "status": "completed",
            "conclusion": "success",
        }
        for i, name in enumerate(names)
    ]
    check = {
        "id": 1003,
        "name": "required",
        "status": "completed",
        "conclusion": "success",
        "head_sha": candidate.sha,
        "app": {"id": 15368},
        "check_suite": {"id": 800},
    }
    return run, jobs, check


def effective_rules():
    common = {"ruleset_id": 99, "ruleset_source": REPO, "ruleset_source_type": "Repository"}
    return [
        {
            **common,
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "required_review_thread_resolution": True,
                "allowed_merge_methods": ["squash"],
            },
        },
        {
            **common,
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": [{"context": "required", "integration_id": 15368}],
            },
        },
        {**common, "type": "non_fast_forward"},
        {**common, "type": "deletion"},
    ]


class GateTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("benchmark.result_pr_checks")
        except ModuleNotFoundError:
            self.fail("result-PR gate implementation required")

    def test_exact_pr_is_accepted_and_mutations_are_rejected(self):
        gate = self.module()
        good = pull_request()
        gate.validate_pr(good, CANDIDATE, 63)
        for path, value in [
            (("number",), True),
            (("number",), 64),
            (("draft",), True),
            (("head", "sha"), "e" * 40),
            (("head", "ref"), "ordinary-code"),
            (("head", "repo", "full_name"), "foreign/repo"),
            (("base", "sha"), "f" * 40),
            (("base", "ref"), "other"),
            (("base", "repo", "full_name"), "foreign/repo"),
            (("commits",), 2),
            (("changed_files",), 8),
            (("state",), "closed"),
        ]:
            bad = copy.deepcopy(good)
            target = bad
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(BenchmarkFailure):
                gate.validate_pr(bad, CANDIDATE, 63)

    def test_only_complete_literal_success_ci_is_accepted(self):
        gate = self.module()
        run, jobs, check = ci_evidence()
        gate.validate_ci(run, jobs, check, CANDIDATE, 63)
        for conclusion in ("failure", "cancelled", "skipped", "neutral", "timed_out", None):
            for where in ("run", "job", "check"):
                r, j, c = copy.deepcopy((run, jobs, check))
                {"run": r, "job": j[0], "check": c}[where]["conclusion"] = conclusion
                with (
                    self.subTest(conclusion=conclusion, where=where),
                    self.assertRaises(BenchmarkFailure),
                ):
                    gate.validate_ci(r, j, c, CANDIDATE, 63)
        for changed in (jobs[:-1], jobs + [jobs[0]], [], [{**j, "run_id": 901} for j in jobs]):
            with self.subTest(jobs=changed), self.assertRaises(BenchmarkFailure):
                gate.validate_ci(run, changed, check, CANDIDATE, 63)

    def test_wrong_ci_identity_or_check_issuer_never_qualifies(self):
        gate = self.module()
        run, jobs, check = ci_evidence()
        for key, value in (
            ("head_sha", "e" * 40),
            ("head_branch", "other"),
            ("event", "push"),
            ("path", ".github/workflows/evil.yml"),
            ("run_attempt", 2),
            ("run_attempt", True),
            ("name", "other"),
            ("head_repository", {"full_name": "other/repo"}),
            ("repository", {"full_name": "other/repo"}),
            ("pull_requests", []),
        ):
            with self.subTest(key=key), self.assertRaises(BenchmarkFailure):
                gate.validate_ci({**run, key: value}, jobs, check, CANDIDATE, 63)
        for key, value in (
            ("app", {"id": 1}),
            ("check_suite", {"id": 801}),
            ("id", 1000),
            ("head_sha", "f" * 40),
            ("status", "in_progress"),
        ):
            with self.subTest(check=key), self.assertRaises(BenchmarkFailure):
                gate.validate_ci(run, jobs, {**check, key: value}, CANDIDATE, 63)

    def test_publication_commit_must_have_exact_tree_and_sole_source_parent(self):
        gate = self.module()
        commit = {
            "sha": "e" * 40,
            "tree": {"sha": CANDIDATE.tree},
            "parents": [{"sha": CANDIDATE.source}],
        }
        self.assertEqual(gate.validate_merge(commit, CANDIDATE), "e" * 40)
        for change in (
            {"tree": {"sha": "f" * 40}},
            {"parents": []},
            {"parents": [{"sha": "f" * 40}]},
            {"parents": commit["parents"] * 2},
            {"sha": "invalid"},
        ):
            with self.subTest(change=change), self.assertRaises(BenchmarkFailure):
                gate.validate_merge({**commit, **change}, CANDIDATE)

    def test_effective_rule_gate_requires_strict_main_policy(self):
        gate = self.module()
        good = effective_rules()
        gate.validate_rules(good, 99)
        for index in range(len(good)):
            with self.subTest(missing=index), self.assertRaises(BenchmarkFailure):
                gate.validate_rules(good[:index] + good[index + 1 :], 99)
        for parameters in (
            {"strict_required_status_checks_policy": False},
            {"required_status_checks": [{"context": "required", "integration_id": 1}]},
        ):
            bad = copy.deepcopy(good)
            bad[1]["parameters"].update(parameters)
            with self.assertRaises(BenchmarkFailure):
                gate.validate_rules(bad, 99)
        with self.assertRaises(BenchmarkFailure):
            gate.validate_rules(good, 98)

    def test_malformed_payloads_are_explicit_gate_failures(self):
        gate = self.module()
        for payload in ({}, [], None, "bad"):
            with self.subTest(payload=payload), self.assertRaises(BenchmarkFailure):
                gate.validate_pr(payload, CANDIDATE, 63)
            with self.subTest(payload=payload), self.assertRaises(BenchmarkFailure):
                gate.validate_merge(payload, CANDIDATE)

    def test_malformed_job_names_and_boolean_check_ids_are_rejected(self):
        gate = self.module()
        run, jobs, check = ci_evidence()
        for value in ([], {}, None, True):
            bad = copy.deepcopy(jobs)
            bad[0]["name"] = value
            with self.subTest(value=value), self.assertRaises(BenchmarkFailure):
                gate.validate_ci(run, bad, check, CANDIDATE, 63)
        jobs[3]["id"] = 1
        check["id"] = True
        with self.assertRaises(BenchmarkFailure):
            gate.validate_ci(run, jobs, check, CANDIDATE, 63)


if __name__ == "__main__":
    unittest.main()
