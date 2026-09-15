"""Authorize reusable Pages calls without changing the caller's GitHub context.

Only the trusted caller revision is executed. The content revision is separately
bound to current main and, for official calls, to the original verified producer.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from .generate_readme import render, replace_section
from .official import trusted_context
from .pages import REF, sha, validate_event
from .publication import expected_publication_paths, history_path
from .readme_charts import render_charts
from .report import REPOSITORY, validate_report
from .results import BenchmarkFailure, require, strict_json
from .site import build as build_site

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "caller",
    "target_sha",
    "source_sha",
    "producer_run_id",
    "producer_run_attempt",
    "producer_result",
)


def number(value, label: str) -> str:
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None, label)
    return value


def git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BenchmarkFailure("Pages Git inspection failed") from error
    require(result.returncode == 0, "Pages Git inspection failed: " + args[0])
    return result.stdout


def git_text(root: Path, *args: str) -> str:
    return git(root, *args).decode("utf-8").strip()


def request_context(root: Path, environment, event, request) -> dict | None:
    """Validate all inputs and the controller identity before touching target content."""
    require(type(request) is dict and set(request) == set(FIELDS), "invalid Pages call inputs")
    require(all(type(value) is str for value in request.values()), "Pages inputs must be strings")
    target = sha(request["target_sha"], "invalid Pages target SHA")
    head = git_text(root, "rev-parse", "HEAD")
    require(environment.get("GITHUB_SHA") == head, "controller/event SHA mismatch")
    require(type(event) is dict, "invalid Pages event")
    repository = event.get("repository")
    require(type(repository) is dict, "missing Pages repository")
    require(repository.get("full_name") == REPOSITORY, "foreign Pages repository")
    require(repository.get("default_branch") == "main", "unexpected default branch")
    number(environment.get("GITHUB_RUN_ID"), "invalid caller run ID")
    attempt = number(environment.get("GITHUB_RUN_ATTEMPT"), "invalid caller attempt")

    if request["caller"] == "pages":
        require(target == head, "ordinary Pages target must match caller SHA")
        require(all(request[field] == "" for field in FIELDS[2:]), "unexpected producer inputs")
        if environment.get("GITHUB_EVENT_NAME") == "workflow_run":
            run = event.get("workflow_run")
            require(type(run) is dict and run.get("name") == "CI", "only CI uses Pages events")
        validate_event(environment, event, head=head)
        return None

    require(request["caller"] == "official", "unknown Pages caller")
    context = trusted_context(environment)
    require(request["source_sha"] == head, "producer source mismatch")
    require(request["producer_result"] == "success", "publication producer did not succeed")
    require(request["producer_run_id"] == context["run_id"], "producer run ID mismatch")
    producer_attempt = number(request["producer_run_attempt"], "invalid producer attempt")
    require(int(producer_attempt) <= int(attempt), "producer attempt is newer than caller")
    # A deployment-only retry increments the caller attempt, not the measurement's.
    # Construct an expected report context; never overwrite GITHUB_* variables.
    return {**context, "run_attempt": producer_attempt}


def regular_blob(root: Path, revision: str, path: str) -> bytes:
    entry = git_text(root, "ls-tree", revision, "--", path)
    require(
        entry.startswith("100644 blob ") and entry.endswith("\t" + path),
        "invalid publication file: " + path,
    )
    return git(root, "show", f"{revision}:{path}")


def verify(root: Path, environment, event, request) -> str:
    """Re-fetch only trusted main; reject stale work before build AND deployment."""
    expected = request_context(root, environment, event, request)
    target = request["target_sha"]
    # No caller-controlled refs/URLs, no checkout of a PR revision, no credentials
    # persisted by this module. The repository is public and checkout is read-only.
    git(root, "fetch", "--no-tags", "--depth=2", "origin", REF)
    require(
        git_text(root, "rev-parse", "FETCH_HEAD") == target,
        "main advanced; refuse stale Pages deployment",
    )
    if expected is None:
        return target

    source = expected["source_commit"]
    require(
        git_text(root, "rev-list", "--parents", "-n", "1", target).split() == [target, source],
        "publication parent mismatch",
    )
    raw = regular_blob(root, target, "results/latest.json")
    report = strict_json(raw)
    validate_report(report, expected_context=expected)
    require(
        report["metadata"]["source_tree"] == git_text(root, "rev-parse", source + "^{tree}"),
        "measured source tree mismatch",
    )
    changed = git_text(
        root, "diff-tree", "--no-commit-id", "--name-only", "-r", target
    ).splitlines()
    require(
        len(changed) == len(set(changed)) and set(changed) == expected_publication_paths(report),
        "publication manifest mismatch",
    )
    # Validate content as well as names: this is the actual immutable transaction,
    # not an arbitrary commit with a similar-looking report or forged job output.
    require(regular_blob(root, target, history_path(report)) == raw, "history content mismatch")
    for path, locale in (("README.md", "en"), ("README.ja.md", "ja")):
        original = regular_blob(root, source, path).decode("utf-8")
        generated = replace_section(original, render(report, locale)).encode("utf-8")
        require(regular_blob(root, target, path) == generated, "README content mismatch")
    for path, content in render_charts(report).items():
        require(
            regular_blob(root, target, path) == content.encode("utf-8"), "chart content mismatch"
        )
    return target


def prepare(root: Path, environment, event, request, output: Path) -> Path:
    target = verify(root, environment, event, request)
    destination = root / ".cache/pages-source"
    require(
        not destination.exists() and not destination.is_symlink(), "Pages workspace already exists"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "--detach", str(destination), target)
    built = build_site(destination)
    # The deploy job consumes this build output, not its current retry attempt.
    name = (
        f"github-pages-{target}-{environment['GITHUB_RUN_ID']}-{environment['GITHUB_RUN_ATTEMPT']}"
    )
    require(output.is_file() and not output.is_symlink(), "invalid Pages output file")
    with output.open("a", encoding="utf-8") as stream:
        stream.write(f"artifact_name={name}\n")
    return built


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "verify"))
    args = parser.parse_args(argv)
    try:
        require(
            git_text(ROOT, "remote", "get-url", "origin")
            in (f"https://github.com/{REPOSITORY}", f"https://github.com/{REPOSITORY}.git"),
            "unexpected Pages remote",
        )
        path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
        require(path.is_file() and not path.is_symlink(), "invalid event payload path")
        event = strict_json(path.read_bytes())
        request = {field: os.environ.get("PAGES_" + field.upper(), "") for field in FIELDS}
        if args.operation == "build":
            prepare(ROOT, os.environ, event, request, Path(os.environ.get("GITHUB_OUTPUT", "")))
        else:
            verify(ROOT, os.environ, event, request)
        print("Verified current-main Pages content: " + request["target_sha"])
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Pages handoff failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
