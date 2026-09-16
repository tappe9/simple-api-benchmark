"""Prepare, wait for and squash only the same run's audited result transaction.

The controller always runs at the measured trusted-main revision. Result-PR code
is never checked out or executed here. Live activation additionally requires the
owner's no-bypass policy audit and actual strict-base race test; local service
models do not prove GitHub enforcement.
"""

import argparse
import base64
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from .github_api import APIError, GitHubAPI
from .official import trusted_context
from .publish import Candidate, git, prepare_candidate
from .report import REPOSITORY, read_regular
from .result_pr_checks import (
    field,
    positive,
    sha,
    validate_ci,
    validate_merge,
    validate_pr,
    validate_rules,
)
from .results import BenchmarkFailure, require, strict_json
from .run import ROOT


def number(value: str, label: str) -> int:
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None, label)
    return int(value)


def publication_mode(environment) -> str:
    mode = environment.get("RESULT_PUBLICATION_MODE") or "legacy"
    require(mode in ("legacy", "pull-request-v1"), "unknown result publication mode")
    if mode == "pull-request-v1":
        require(
            environment.get("RESULT_PR_ROLLOUT_APPROVED") == "strict-main-v1",
            "PR publishing rollout not approved",
        )
        number(environment.get("RESULT_PR_RULESET_ID", ""), "approved main ruleset ID required")
    return mode


def main_sha(api: GitHubAPI) -> str:
    ref = api.request("GET", "git/ref/heads/main")
    require(field(ref, "ref") == "refs/heads/main", "unexpected main ref")
    require(field(ref, "object", "type") == "commit", "invalid main object")
    return sha(field(ref, "object", "sha"))


def require_current(api: GitHubAPI, candidate: Candidate) -> None:
    require(main_sha(api) == candidate.source, "main advanced; refuse stale result, do not rebase")


def branch_sha(api: GitHubAPI, candidate: Candidate) -> str | None:
    try:
        ref = api.request("GET", "git/ref/heads/" + quote(candidate.branch, safe="/"))
    except APIError as error:
        if error.status == 404:
            return None
        raise
    require(field(ref, "ref") == "refs/heads/" + candidate.branch, "unexpected candidate ref")
    require(field(ref, "object", "type") == "commit", "invalid candidate object")
    return sha(field(ref, "object", "sha"))


def existing_pr(api: GitHubAPI, candidate: Candidate) -> int | None:
    query = urlencode(
        {"state": "all", "base": "main", "head": REPOSITORY.split("/")[0] + ":" + candidate.branch}
    )
    prs = api.pages("pulls?" + query)
    require(len(prs) <= 1, "multiple result PRs; reconcile manually")
    return None if not prs else positive(field(prs[0], "number"), "invalid PR number")


def read_pr(api: GitHubAPI, candidate: Candidate, number: int) -> dict:
    positive(number, "invalid PR number")
    pr = api.request("GET", f"pulls/{number}")
    is_merged = field(pr, "merged")
    require(type(is_merged) is bool, "malformed merged flag")
    validate_pr(pr, candidate, number, merged=is_merged)
    return pr


def merged_identity(api: GitHubAPI, candidate: Candidate, pr: dict) -> str:
    commit = sha(field(pr, "merge_commit_sha"))
    record = api.request("GET", "git/commits/" + commit)
    require(field(record, "sha") == commit, "unexpected merge object")
    return validate_merge(record, candidate)


def propose(
    root: Path, candidate: Candidate, reader: GitHubAPI, writer: GitHubAPI, *, git_environment=None
) -> int:
    # A reconstructed candidate is content-bound, not trusted from a label or bot name.
    existing = existing_pr(reader, candidate)
    if existing is not None:
        pr = read_pr(reader, candidate, existing)
        if pr["merged"]:
            merged_identity(reader, candidate, pr)
            return existing
    require_current(reader, candidate)
    remote = branch_sha(reader, candidate)
    require(remote is None or remote == candidate.sha, "result branch changed; never overwrite")
    if remote is None:
        try:
            # Never force: Git rejects a divergent concurrent branch update.
            git(
                root,
                "push",
                "origin",
                f"{candidate.sha}:refs/heads/{candidate.branch}",
                environment=git_environment,
            )
        except BenchmarkFailure:
            # A missing response can follow a successful write. Read, do not retry blindly.
            require(
                branch_sha(reader, candidate) == candidate.sha,
                "candidate push failed; reconcile remote branch",
            )
    require(branch_sha(reader, candidate) == candidate.sha, "candidate push identity mismatch")
    require_current(reader, candidate)
    if existing is None:
        try:
            created = writer.request(
                "POST",
                "pulls",
                {
                    "head": candidate.branch,
                    "base": "main",
                    "draft": False,
                    "maintainer_can_modify": False,
                    "title": f"results: publish verified run {candidate.run_id}/{candidate.run_attempt}",
                    "body": (
                        "Generated only from audited official evidence.\n\n"
                        f"Measured source: `{candidate.source}`\n"
                        f"Candidate: `{candidate.sha}`\nAudited tree: `{candidate.tree}`\n\n"
                        "Full CI and strict main freshness are required. Do not rebase, edit, "
                        "or manually update this branch to bypass a stale-source rejection."
                    ),
                },
            )
            existing = positive(field(created, "number"), "invalid created PR")
        except APIError as error:
            existing = existing_pr(reader, candidate)
            require(existing is not None, f"PR creation failed ({error}); reconcile before retry")
    read_pr(reader, candidate, existing)
    return existing


def ci_run(api: GitHubAPI, candidate: Candidate) -> dict | None:
    query = urlencode({"event": "pull_request", "head_sha": candidate.sha})
    runs = api.pages("actions/workflows/ci.yml/runs?" + query, "workflow_runs")
    if not runs:
        return None
    # Never fall back to an older green run when a newer run failed or is pending.
    return max(runs, key=lambda run: positive(field(run, "id"), "invalid CI run ID"))


def successful_ci(api: GitHubAPI, candidate: Candidate, number: int, run: dict) -> int:
    run_id = positive(field(run, "id"), "invalid CI run ID")
    attempt = positive(field(run, "run_attempt"), "invalid CI attempt")
    jobs = api.pages(f"actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    required = [job for job in jobs if field(job, "name") == "required"]
    require(len(required) == 1, "missing or duplicate required job")
    check_id = positive(field(required[0], "id"), "invalid check ID")
    check = api.request("GET", f"check-runs/{check_id}")
    validate_ci(run, jobs, check, candidate, number)
    return run_id


def wait(
    candidate: Candidate, number: int, reader: GitHubAPI, *, polls: int = 80, sleep=time.sleep
) -> int:
    require(type(polls) is int and 0 < polls <= 80, "invalid CI wait budget")
    for index in range(polls):
        pr = read_pr(reader, candidate, number)
        if pr["merged"]:
            merged_identity(reader, candidate, pr)
            return 0  # A retry can reconcile the already committed transaction in merge.
        require_current(reader, candidate)
        run = ci_run(reader, candidate)
        if run is not None:
            state = field(run, "status")
            if state == "completed":
                return successful_ci(reader, candidate, number, run)
            require(
                state in ("queued", "in_progress", "waiting", "pending", "requested"),
                "unknown CI state",
            )
        if index + 1 < polls:
            sleep(15)
    raise BenchmarkFailure("result PR CI wait timed out; no merge attempted")


def merge(
    candidate: Candidate, number: int, reader: GitHubAPI, writer: GitHubAPI, *, ruleset_id: int
) -> str:
    pr = read_pr(reader, candidate, number)
    if pr["merged"]:
        # Publication succeeded previously; outputs may have been lost. Never publish again.
        return merged_identity(reader, candidate, pr)
    require_current(reader, candidate)
    validate_rules(reader.pages("rules/branches/main"), ruleset_id)
    run = ci_run(reader, candidate)
    require(run is not None, "CI not found")
    successful_ci(reader, candidate, number, run)
    # Recheck after the potentially slow CI reads and before the only main write.
    pr = read_pr(reader, candidate, number)
    require(
        field(pr, "mergeable") is True and field(pr, "mergeable_state") == "clean",
        "PR is not merge-ready under current policy",
    )
    require_current(reader, candidate)
    try:
        response = writer.request(
            "PUT",
            f"pulls/{number}/merge",
            {
                "sha": candidate.sha,
                "merge_method": "squash",
                "commit_title": "chore: publish verified benchmark results",
                "commit_message": f"Measured source: {candidate.source}\nOfficial run: {candidate.run_id}/{candidate.run_attempt}\n",
            },
        )
    except APIError as error:
        pr = read_pr(reader, candidate, number)
        require(
            pr["merged"] is True,
            f"merge denied or response lost ({error}); reconcile, never direct-push",
        )
        return merged_identity(reader, candidate, pr)
    require(field(response, "merged") is True, "result PR was not merged")
    commit = sha(field(response, "sha"))
    pr = read_pr(reader, candidate, number)
    require(
        pr["merged"] is True and field(pr, "merge_commit_sha") == commit,
        "merge response identity mismatch",
    )
    return merged_identity(reader, candidate, pr)


def outputs(values: dict) -> None:
    path = Path(os.environ.get("GITHUB_OUTPUT", ""))
    require(path.is_file() and not path.is_symlink(), "publication output file required")
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            require(re.fullmatch(r"[a-z_]+", key) is not None, "invalid output key")
            require(re.fullmatch(r"[a-z0-9-]+", str(value)) is not None, "invalid output value")
            stream.write(f"{key}={value}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preflight", "propose", "wait", "merge"))
    args = parser.parse_args(argv)
    try:
        context = trusted_context()
        mode = publication_mode(os.environ)
        if args.operation == "preflight":
            if mode == "pull-request-v1":
                reader = GitHubAPI(os.environ.get("GH_READ_TOKEN", ""))
                ruleset_id = number(
                    os.environ.get("RESULT_PR_RULESET_ID", ""), "ruleset ID required"
                )
                validate_rules(reader.pages("rules/branches/main"), ruleset_id)
            outputs({"mode": mode, "producer_run_attempt": context["run_attempt"]})
            print("Validated publication mode: " + mode)
            return 0
        require(mode == "pull-request-v1", "PR controller is inactive")
        attempt = number(
            os.environ.get("PUBLICATION_ATTEMPT", ""), "original measurement attempt required"
        )
        require(
            attempt <= int(context["run_attempt"]), "measurement attempt is newer than controller"
        )
        context = {**context, "run_attempt": str(attempt)}
        require(
            git(ROOT, "remote", "get-url", "origin")
            in (f"https://github.com/{REPOSITORY}", f"https://github.com/{REPOSITORY}.git"),
            "unexpected publication remote",
        )
        report = strict_json(read_regular(ROOT / ".cache/official/selected.json", ROOT))
        candidate = prepare_candidate(report, ROOT, expected_context=context)
        reader = GitHubAPI(os.environ.get("GH_READ_TOKEN", ""))
        if args.operation == "wait":
            number_ = number(os.environ.get("RESULT_PR_NUMBER", ""), "result PR number required")
            wait(candidate, number_, reader)
            print("Result PR validation completed")
            return 0
        writer = GitHubAPI(os.environ.get("PUBLISHER_TOKEN", ""))
        ruleset_id = number(os.environ.get("RESULT_PR_RULESET_ID", ""), "ruleset ID required")
        if args.operation == "propose":
            validate_rules(reader.pages("rules/branches/main"), ruleset_id)
            environment = dict(os.environ)
            authorization = base64.b64encode(
                ("x-access-token:" + os.environ["PUBLISHER_TOKEN"]).encode()
            ).decode()
            environment.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + authorization,
            )
            number_ = propose(ROOT, candidate, reader, writer, git_environment=environment)
            outputs({"pr_number": number_})
            print(f"Audited result PR: {number_}")
        else:
            number_ = number(os.environ.get("RESULT_PR_NUMBER", ""), "result PR number required")
            commit = merge(candidate, number_, reader, writer, ruleset_id=ruleset_id)
            try:
                outputs(
                    {
                        "publication_sha": commit,
                        "source_sha": candidate.source,
                        "producer_run_id": candidate.run_id,
                        "producer_run_attempt": candidate.run_attempt,
                    }
                )
            except (OSError, BenchmarkFailure):
                raise BenchmarkFailure(
                    "result is published but outputs failed; recover Pages without remeasurement"
                ) from None
            print("Verified merged publication: " + commit)
        return 0
    except (BenchmarkFailure, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Result PR publication stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
