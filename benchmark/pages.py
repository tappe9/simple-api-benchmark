"""Authorize Pages builds only for validated trusted-main workflow events."""

import os
import re
import subprocess
import sys
from pathlib import Path

from .report import REPOSITORY, validate_report
from .results import BenchmarkFailure, require, strict_json

ROOT = Path(__file__).resolve().parents[1]
REF = "refs/heads/main"
WORKFLOW = REPOSITORY + "/.github/workflows/pages.yml@" + REF
CI_PATH = ".github/workflows/ci.yml"
BENCHMARK_PATH = ".github/workflows/benchmark.yml"


def text(value, label: str) -> str:
    require(type(value) is str and bool(value), label)
    return value


def sha(value, label: str) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None, label)
    return value


def validate_event(environment, event, *, head: str, parents=(), changed=(), report=None) -> None:
    required = (
        "GITHUB_ACTIONS",
        "GITHUB_REPOSITORY",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_EVENT_NAME",
    )
    for key in required:
        text(environment.get(key), "missing " + key)
    require(environment["GITHUB_ACTIONS"] == "true", "Pages requires GitHub Actions")
    require(environment["GITHUB_REPOSITORY"] == REPOSITORY, "unexpected repository")
    require(environment["GITHUB_REF"] == REF, "Pages requires default branch")
    sha(head, "invalid checkout head")
    require(environment["GITHUB_SHA"] == head, "checkout/event SHA mismatch")
    require(environment["GITHUB_WORKFLOW_SHA"] == head, "workflow/source mismatch")
    require(environment["GITHUB_WORKFLOW_REF"] == WORKFLOW, "unexpected Pages workflow")

    require(type(event) is dict, "invalid event payload")
    repository = event.get("repository")
    require(type(repository) is dict, "missing event repository")
    require(repository.get("full_name") == REPOSITORY, "foreign event repository")
    require(repository.get("default_branch") == "main", "unexpected default branch")

    event_name = environment["GITHUB_EVENT_NAME"]
    require(event_name in ("workflow_run", "workflow_dispatch"), "untrusted Pages event")
    if event_name == "workflow_dispatch":
        return

    run = event.get("workflow_run")
    require(type(run) is dict, "missing workflow run")
    require(run.get("status") == "completed", "upstream workflow is not complete")
    require(run.get("conclusion") == "success", "upstream workflow did not succeed")
    require(run.get("head_branch") == "main", "upstream branch is not main")
    upstream_repository = run.get("head_repository")
    require(type(upstream_repository) is dict, "missing upstream repository")
    require(upstream_repository.get("full_name") == REPOSITORY, "foreign upstream repository")

    name = run.get("name")
    path = run.get("path")
    if name == "CI":
        require(path == CI_PATH, "unexpected CI workflow path")
        require(run.get("event") == "push", "Pages CI source must be a main push")
        require(run.get("head_sha") == head, "stale CI workflow run")
        return

    require(name == "Official benchmark", "untrusted upstream workflow")
    require(path == BENCHMARK_PATH, "unexpected benchmark workflow path")
    require(run.get("event") in ("schedule", "workflow_dispatch"), "untrusted benchmark event")
    require(report is not None, "official publication requires verified result")
    validate_report(report)
    context = report["metadata"]["github"]
    source = report["metadata"]["source_commit"]
    require(run.get("head_sha") == source, "benchmark source mismatch")
    require(run.get("event") == context["event"], "benchmark event mismatch")
    require(run.get("id") == int(context["run_id"]), "benchmark run ID mismatch")
    require(run.get("run_attempt") == int(context["run_attempt"]), "benchmark attempt mismatch")
    require(
        list(parents) == [source], "publication commit must have measured source as sole parent"
    )

    paths = list(changed)
    require(len(paths) == 4, "official publication must change exactly four files")
    fixed = {"README.md", "README.ja.md", "results/latest.json"}
    require(fixed <= set(paths), "official publication files missing")
    history = [
        path for path in paths if path.startswith("results/history/") and path.endswith(".json")
    ]
    require(len(history) == 1 and set(paths) == fixed | set(history), "unexpected publication path")


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BenchmarkFailure("Git inspection failed") from error
    require(result.returncode == 0, f"Git inspection failed: {args[0]}")
    return result.stdout.decode().strip()


def main() -> int:
    try:
        event_path = Path(text(os.environ.get("GITHUB_EVENT_PATH"), "missing GITHUB_EVENT_PATH"))
        require(not event_path.is_symlink() and event_path.is_file(), "invalid event payload path")
        event = strict_json(event_path.read_bytes())
        head = git("rev-parse", "HEAD")
        line = git("rev-list", "--parents", "-n", "1", "HEAD").split()
        require(bool(line) and line[0] == head, "invalid Git parent data")
        parents = line[1:]
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        report_path = ROOT / "results/latest.json"
        report = strict_json(report_path.read_bytes()) if report_path.is_file() else None
        validate_event(
            os.environ, event, head=head, parents=parents, changed=changed, report=report
        )
        print("Trusted main content authorized for Pages publication.")
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Pages authorization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
