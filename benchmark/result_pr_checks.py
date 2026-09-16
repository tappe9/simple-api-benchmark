"""Fail-closed identity checks for an audited result PR (no network or writes)."""

import re

from .publication import CHART_PUBLICATION_PATHS, FIXED_PUBLICATION_PATHS
from .publish import Candidate
from .registry import load_registry
from .report import REPOSITORY
from .results import require

ACTIONS_APP_ID = 15368


def field(value, *path):
    """Turn absent/wrong-shaped API evidence into a controlled rejection."""
    for key in path:
        require(type(value) is dict and key in value, "missing or malformed API evidence")
        value = value[key]
    return value


def positive(value, label: str) -> int:
    require(type(value) is int and 0 < value < 10**20, label)
    return value


def sha(value) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None, "invalid SHA")
    return value


def validate_pr(pr, candidate: Candidate, number: int, *, merged: bool = False) -> None:
    require(positive(field(pr, "number"), "invalid PR number") == number, "wrong PR number")
    require(field(pr, "draft") is False, "result PR is a draft")
    require(field(pr, "state") == ("closed" if merged else "open"), "unexpected PR state")
    require(field(pr, "merged") is merged, "unexpected merge state")
    for side in ("head", "base"):
        require(field(pr, side, "repo", "full_name") == REPOSITORY, "foreign result PR")
    require(field(pr, "head", "ref") == candidate.branch, "wrong result branch")
    require(field(pr, "head", "sha") == candidate.sha, "result PR head changed")
    require(field(pr, "base", "ref") == "main", "wrong PR base")
    if not merged:
        require(field(pr, "base", "sha") == candidate.source, "main advanced; refuse stale result")
    require(type(field(pr, "commits")) is int and pr["commits"] == 1, "unexpected PR commits")
    require(
        type(field(pr, "changed_files")) is int
        and pr["changed_files"] == len(FIXED_PUBLICATION_PATHS | CHART_PUBLICATION_PATHS) + 1,
        "unexpected PR paths",
    )


def validate_ci(run, jobs, check, candidate: Candidate, number: int) -> None:
    run_id = positive(field(run, "id"), "invalid CI run")
    attempt = positive(field(run, "run_attempt"), "invalid CI attempt")
    expected = {
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "head_branch": candidate.branch,
        "head_sha": candidate.sha,
        "status": "completed",
        "conclusion": "success",
    }
    require(
        all(field(run, key) == value for key, value in expected.items()),
        "CI is not exact successful PR CI",
    )
    for key in ("repository", "head_repository"):
        require(field(run, key, "full_name") == REPOSITORY, "foreign CI repository")
    prs = field(run, "pull_requests")
    require(type(prs) is list and len(prs) == 1, "ambiguous CI PR identity")
    require(field(prs[0], "number") == number, "CI belongs to another PR")
    require(field(prs[0], "head", "sha") == candidate.sha, "CI tested another head")
    require(field(prs[0], "base", "sha") == candidate.source, "CI tested another base")
    require(type(jobs) is list, "malformed CI jobs")
    expected_names = {"plan", "shared", "smoke", "required"} | {
        f"implementation ({spec['id']})" for spec in load_registry()["implementations"]
    }
    names = [field(job, "name") for job in jobs]
    require(all(type(name) is str for name in names), "malformed CI job name")
    require(
        len(names) == len(expected_names) and set(names) == expected_names,
        "missing or duplicate CI jobs",
    )
    for job in jobs:
        require(positive(field(job, "run_id"), "invalid job run") == run_id, "wrong job run")
        require(
            positive(field(job, "run_attempt"), "invalid job attempt") == attempt,
            "wrong job attempt",
        )
        require(field(job, "head_sha") == candidate.sha, "job tested another head")
        require(
            field(job, "status") == "completed" and field(job, "conclusion") == "success",
            "CI job did not succeed",
        )
    required = next(job for job in jobs if job["name"] == "required")
    require(
        positive(field(check, "id"), "invalid check ID")
        == positive(field(required, "id"), "invalid required job"),
        "wrong required check",
    )
    require(field(check, "name") == "required", "wrong check name")
    require(field(check, "app", "id") == ACTIONS_APP_ID, "wrong check issuer")
    require(
        field(check, "check_suite", "id")
        == positive(field(run, "check_suite_id"), "invalid suite"),
        "wrong check suite",
    )
    require(field(check, "head_sha") == candidate.sha, "check tested another head")
    require(
        field(check, "status") == "completed" and field(check, "conclusion") == "success",
        "required check did not succeed",
    )


def validate_merge(commit, candidate: Candidate) -> str:
    merged = sha(field(commit, "sha"))
    require(
        field(commit, "tree", "sha") == candidate.tree, "published tree differs from audited result"
    )
    parents = field(commit, "parents")
    require(type(parents) is list and len(parents) == 1, "publication must have one parent")
    require(
        field(parents[0], "sha") == candidate.source,
        "publication parent differs from measured source",
    )
    return merged


def validate_rules(rules, ruleset_id: int) -> None:
    """Check public effective rules; private bypass/environment audit is owner-only."""
    positive(ruleset_id, "invalid ruleset ID")
    require(type(rules) is list, "malformed effective rules")
    selected = {}
    for rule in rules:
        if field(rule, "ruleset_id") != ruleset_id:
            continue
        require(field(rule, "ruleset_source_type") == "Repository", "foreign ruleset scope")
        require(field(rule, "ruleset_source") == REPOSITORY, "foreign ruleset source")
        kind = field(rule, "type")
        require(type(kind) is str and kind not in selected, "duplicate or malformed rule")
        selected[kind] = rule
    require(
        {"pull_request", "required_status_checks", "non_fast_forward", "deletion"}
        <= selected.keys(),
        "required effective main policy missing",
    )
    checks = field(selected["required_status_checks"], "parameters")
    require(
        field(checks, "strict_required_status_checks_policy") is True, "strict freshness required"
    )
    require(field(checks, "do_not_enforce_on_create") is False, "check enforcement required")
    require(
        field(checks, "required_status_checks")
        == [{"context": "required", "integration_id": ACTIONS_APP_ID}],
        "wrong required check policy",
    )
    pr = field(selected["pull_request"], "parameters")
    require(
        field(pr, "required_review_thread_resolution") is True, "conversation resolution required"
    )
    require(field(pr, "allowed_merge_methods") == ["squash"], "squash-only policy required")
    count = field(pr, "required_approving_review_count")
    require(type(count) is int and count == 0, "unexpected review policy")
