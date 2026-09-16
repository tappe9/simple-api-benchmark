"""Pure result-PR preflight; no HTTP, token access, ref update or merge execution.

Callers must first rebuild/verify the candidate from trusted source and raw evidence.
Snapshots must come from complete, fresh authenticated API reads, not a PR's body,
labels or artifacts. A plan is not a lock: live integration requires verified strict
server-side base protection, race tests, and a last-moment re-read before any write.
"""

import re
from dataclasses import dataclass

from .ci import matrix_payload
from .publication_candidate import PublicationCandidate
from .report import REPOSITORY
from .results import BenchmarkFailure

REPOSITORY_ID = 1356993741
ACTIONS_APP_ID = 15368
CI_WORKFLOW_ID = 350921839
CI_PATH = ".github/workflows/ci.yml"
RULE_TYPES = frozenset({"pull_request", "required_status_checks", "non_fast_forward", "deletion"})


class ResultPRFailure(BenchmarkFailure):
    """Machine-readable rejection with a fixed message, never arbitrary API text."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ResultPRFailure(code, message)


def _object(value, code: str) -> dict:
    _require(type(value) is dict, code, "expected complete object snapshot")
    return value


def _array(value, code: str) -> list:
    _require(type(value) is list, code, "expected complete array snapshot")
    return value


def _positive_id(value, code: str) -> int:
    _require(type(value) is int and 0 < value < 2**63, code, "invalid numeric identity")
    return value


def _repository(value, code: str) -> None:
    repository = _object(value, code)
    _require(
        repository.get("full_name") == REPOSITORY
        and type(repository.get("id")) is int
        and repository["id"] == REPOSITORY_ID,
        code,
        "foreign or missing repository identity",
    )


def _pull_identity(value, candidate: PublicationCandidate) -> int:
    code = "invalid_pr"
    pull = _object(value, code)
    number = _positive_id(pull.get("number"), code)
    for side, ref in (("head", candidate.branch), ("base", "main")):
        branch = _object(pull.get(side), code)
        _repository(branch.get("repo"), code)
        _require(branch.get("ref") == ref, code, "unexpected pull-request ref")
    _require(pull["head"].get("sha") == candidate.commit, code, "pull-request head changed")
    _require(
        type(pull.get("commits")) is int and pull["commits"] == 1,
        code,
        "result transaction must contain exactly one candidate commit",
    )
    return number


def _commit_identity(value, candidate: PublicationCandidate, expected_sha: str, code: str) -> None:
    commit = _object(value, code)
    tree = _object(commit.get("tree"), code)
    parents = _array(commit.get("parents"), code)
    _require(commit.get("sha") == expected_sha, code, "unexpected transaction commit")
    _require(tree.get("sha") == candidate.tree, code, "transaction tree changed")
    _require(len(parents) == 1, code, "transaction must have one measured-source parent")
    _require(
        _object(parents[0], code).get("sha") == candidate.source,
        code,
        "transaction parent differs from measured source",
    )


def expected_job_names() -> frozenset[str]:
    """CI covers every registered implementation, including inactive cohort members."""
    try:
        entries = matrix_payload()["include"]
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        raise ResultPRFailure(
            "invalid_ci", "trusted CI registry is invalid or unsupported"
        ) from error
    return frozenset(
        {"plan", "shared", "smoke", "required"}
        | {f"implementation ({entry['implementation']})" for entry in entries}
    )


def _by_name(value, expected: frozenset[str]) -> dict[str, dict]:
    records = _array(value, "invalid_ci")
    _require(len(records) == len(expected), "invalid_ci", "incomplete or unexpected CI inventory")
    indexed = {}
    identifiers = set()
    for record in records:
        record = _object(record, "invalid_ci")
        name = record.get("name")
        identifier = _positive_id(record.get("id"), "invalid_ci")
        _require(
            type(name) is str and name in expected and name not in indexed,
            "invalid_ci",
            "missing, duplicate or unexpected CI component",
        )
        _require(identifier not in identifiers, "invalid_ci", "duplicate CI component identity")
        indexed[name] = record
        identifiers.add(identifier)
    return indexed


def _successful(value: dict) -> None:
    _require(value.get("status") == "completed", "invalid_ci", "CI component is incomplete")
    _require(value.get("conclusion") == "success", "ci_rejected", "CI component did not succeed")


def _validate_ci(candidate, pull_number: int, value, jobs, checks) -> tuple[int, int]:
    run = _object(value, "invalid_ci")
    run_id = _positive_id(run.get("id"), "invalid_ci")
    attempt = _positive_id(run.get("run_attempt"), "invalid_ci")
    suite = _positive_id(run.get("check_suite_id"), "invalid_ci")
    _repository(run.get("repository"), "invalid_ci")
    _repository(run.get("head_repository"), "invalid_ci")
    expected = {
        "workflow_id": CI_WORKFLOW_ID,
        "name": "CI",
        "path": CI_PATH,
        "event": "pull_request",
        "head_sha": candidate.commit,
        "head_branch": candidate.branch,
    }
    for key, required in expected.items():
        _require(
            _same_json(run.get(key), required),
            "invalid_ci",
            "CI run does not identify this candidate",
        )
    associated = _array(run.get("pull_requests"), "invalid_ci")
    _require(len(associated) == 1, "invalid_ci", "ambiguous or missing CI pull-request association")
    link = _object(associated[0], "invalid_ci")
    _require(
        _positive_id(link.get("number"), "invalid_ci") == pull_number,
        "invalid_ci",
        "CI belongs to another pull request",
    )
    for side, ref, sha in (
        ("head", candidate.branch, candidate.commit),
        ("base", "main", candidate.source),
    ):
        branch = _object(link.get(side), "invalid_ci")
        _require(
            branch.get("sha") == sha
            and branch.get("ref") == ref
            and _positive_id(_object(branch.get("repo"), "invalid_ci").get("id"), "invalid_ci")
            == REPOSITORY_ID,
            "invalid_ci",
            "CI pull-request source changed",
        )
    status = run.get("status")
    _require(type(status) is str, "invalid_ci", "invalid CI run status")
    if status in ("queued", "in_progress", "waiting", "requested", "pending"):
        _require(run.get("conclusion") is None, "invalid_ci", "inconsistent pending CI status")
        raise ResultPRFailure("ci_pending", "CI is pending; no merge plan is available")
    _require(status == "completed", "invalid_ci", "unknown CI status")
    _successful(run)
    names = expected_job_names()
    job_map = _by_name(jobs, names)
    check_map = _by_name(checks, names)
    for name in names:
        job = job_map[name]
        check = check_map[name]
        _require(
            _positive_id(job.get("run_id"), "invalid_ci") == run_id
            and _positive_id(job.get("run_attempt"), "invalid_ci") == attempt
            and job.get("head_sha") == candidate.commit,
            "invalid_ci",
            "job comes from another run, attempt or head",
        )
        _require(
            check["id"] == job["id"]
            and check.get("head_sha") == candidate.commit
            and _positive_id(
                _object(check.get("check_suite"), "invalid_ci").get("id"), "invalid_ci"
            )
            == suite
            and _positive_id(_object(check.get("app"), "invalid_ci").get("id"), "invalid_ci")
            == ACTIONS_APP_ID,
            "invalid_ci",
            "check issuer, suite, job or head mismatch",
        )
        _successful(job)
        _successful(check)
    return run_id, attempt


def _rules_by_type(value) -> dict[str, dict]:
    rules = _array(value, "policy_unverified")
    _require(len(rules) == len(RULE_TYPES), "policy_unverified", "unexpected effective policy")
    indexed = {}
    for rule in rules:
        rule = _object(rule, "policy_unverified")
        kind = rule.get("type")
        _require(
            type(kind) is str and kind in RULE_TYPES and kind not in indexed,
            "policy_unverified",
            "missing, duplicated or unreviewed policy rule",
        )
        indexed[kind] = rule
    return indexed


def _same_json(actual, expected) -> bool:
    """Python's True == 1 is not equality of policy JSON values."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _same_json(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _same_json(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def validate_policy(ruleset, effective_rules) -> int:
    """Validate explicit policy evidence; omitted bypass data is UNKNOWN, never empty.

    GitHub only exposes bypass_actors with ruleset-write access. Do not grant that
    access to the publisher just to satisfy this offline validator. Live integration
    needs a separately reviewed administrative inspection/attestation boundary.
    """
    code = "policy_unverified"
    ruleset = _object(ruleset, code)
    identifier = _positive_id(ruleset.get("id"), code)
    _require(
        ruleset.get("target") == "branch"
        and ruleset.get("source_type") == "Repository"
        and ruleset.get("source") == REPOSITORY
        and ruleset.get("enforcement") == "active",
        code,
        "policy is not active for the expected repository branch",
    )
    _require(ruleset.get("bypass_actors") == [], code, "bypass list is unknown or nonempty")
    conditions = _object(ruleset.get("conditions"), code)
    refs = _object(conditions.get("ref_name"), code)
    _require(
        refs.get("include") == ["refs/heads/main"] and refs.get("exclude") == [],
        code,
        "policy is not scoped exclusively to main",
    )
    rules = _rules_by_type(ruleset.get("rules"))
    checks = _object(rules["required_status_checks"].get("parameters"), code)
    _require(
        checks.get("strict_required_status_checks_policy") is True
        and checks.get("do_not_enforce_on_create") is False
        and _same_json(
            checks.get("required_status_checks"),
            [{"context": "required", "integration_id": ACTIONS_APP_ID}],
        ),
        code,
        "strict required check from GitHub Actions is not enforced",
    )
    pull = _object(rules["pull_request"].get("parameters"), code)
    _require(
        pull.get("allowed_merge_methods") == ["squash"]
        and type(pull.get("required_approving_review_count")) is int
        and pull["required_approving_review_count"] == 0
        and pull.get("required_review_thread_resolution") is True
        and pull.get("require_code_owner_review") is False
        and pull.get("require_last_push_approval") is False
        and pull.get("required_reviewers", []) == [],
        code,
        "pull-request policy differs from the reviewed single-maintainer design",
    )
    active = _rules_by_type(effective_rules)
    for kind, rule in active.items():
        _require(
            _positive_id(rule.get("ruleset_id"), code) == identifier
            and rule.get("ruleset_source") == REPOSITORY
            and rule.get("ruleset_source_type") == "Repository"
            and _same_json(rule.get("parameters", {}), rules[kind].get("parameters", {})),
            code,
            "effective branch rules differ from inspected configuration",
        )
    return identifier


@dataclass(frozen=True)
class MergePlan:
    """A snapshot-derived request, NOT live authority or an atomic base-SHA lock."""

    pull_number: int
    expected_head: str
    expected_source: str
    expected_tree: str
    ci_run_id: int
    ci_run_attempt: int
    ruleset_id: int

    @property
    def request(self) -> dict[str, str]:
        return {"sha": self.expected_head, "merge_method": "squash"}


def plan_merge(
    candidate: PublicationCandidate,
    *,
    pull_request,
    candidate_commit,
    ci_run,
    jobs,
    checks,
    ruleset,
    effective_rules,
    main_sha,
) -> MergePlan:
    """Build no request unless every supplied preflight snapshot passes.

    Re-fetching head/base/CI immediately before a write and proving server-side
    stale-base rejection are integration requirements, not provided by this function.
    """
    _require(type(candidate) is PublicationCandidate, "invalid_candidate", "candidate is required")
    _require(main_sha == candidate.source, "stale_main", "main advanced; do not rebase results")
    number = _pull_identity(pull_request, candidate)
    _require(
        pull_request.get("state") == "open"
        and pull_request.get("merged") is False
        and pull_request.get("draft") is False
        and pull_request["base"].get("sha") == candidate.source,
        "invalid_pr",
        "pull request is not the open, exact-source result candidate",
    )
    _commit_identity(candidate_commit, candidate, candidate.commit, "invalid_candidate")
    run_id, attempt = _validate_ci(candidate, number, ci_run, jobs, checks)
    policy_id = validate_policy(ruleset, effective_rules)
    return MergePlan(
        number, candidate.commit, candidate.source, candidate.tree, run_id, attempt, policy_id
    )


def reconcile_publication(
    candidate: PublicationCandidate,
    *,
    pull_request,
    merged_commit,
) -> dict[str, str]:
    """Reconcile a lost merge response with fresh authoritative reads, without retrying.

    A merged API response alone is insufficient. Only the actual single-parent,
    identical-tree transaction produces Pages outputs. The current main ref may
    have advanced since a valid publication; subsequent stale Pages checks remain
    responsible for deciding whether that transaction may still be deployed.
    """
    _require(type(candidate) is PublicationCandidate, "invalid_candidate", "candidate is required")
    _pull_identity(pull_request, candidate)
    _require(
        pull_request.get("state") == "closed"
        and pull_request.get("merged") is True
        and pull_request.get("draft") is False,
        "invalid_merge",
        "publication is not a confirmed merged result PR; do not retry blindly",
    )
    merged = pull_request.get("merge_commit_sha")
    _require(
        type(merged) is str and re.fullmatch(r"[0-9a-f]{40}", merged) is not None,
        "invalid_merge",
        "missing or invalid merged publication SHA",
    )
    _commit_identity(merged_commit, candidate, merged, "invalid_merge")
    return {
        "publication_sha": merged,
        "source_sha": candidate.source,
        "producer_run_id": candidate.run_id,
        "producer_run_attempt": candidate.run_attempt,
    }
