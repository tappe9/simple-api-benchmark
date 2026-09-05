"""Publish four generated files with one fast-forward Git ref update, never a force push."""

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .generate_readme import render, replace_section
from .official import trusted_context
from .report import REPOSITORY, audit_raw, read_regular, timestamp, validate_report
from .results import BenchmarkFailure, require, strict_json
from .run import ROOT


def git(root: Path, *args: str, data: bytes | None = None, environment=None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BenchmarkFailure(f"Git operation failed: {args[0]}") from error
    # Do not include subprocess output here: transport errors could contain credentials.
    require(result.returncode == 0, f"Git operation failed: {args[0]} (exit {result.returncode})")
    return result.stdout.decode("utf-8").strip()


def history_path(report: dict) -> str:
    date = timestamp(report["completed_at"]).strftime("%Y-%m-%dT%H-%M-%SZ")
    context = report["metadata"]["github"]
    return f"results/history/{date}-{context['run_id']}-{context['run_attempt']}.json"


def publish(report: dict, root: Path, *, expected_context: dict, environment=None) -> str:
    validate_report(report, expected_context=expected_context)
    audit_raw(report, root)
    source = report["metadata"]["source_commit"]
    require(
        git(root, "rev-parse", "HEAD") == source, "publication checkout must match measured source"
    )
    require(
        git(root, "rev-parse", "HEAD^{tree}") == report["metadata"]["source_tree"],
        "source tree mismatch",
    )
    # No worktree changes or user-staged files may enter the transaction.
    require(
        not git(root, "status", "--porcelain", "--untracked-files=normal"),
        "publication needs clean source",
    )
    remote = git(
        root, "ls-remote", "--exit-code", "origin", "refs/heads/main", environment=environment
    )
    require(remote.split()[0] == source, "main advanced; leave verified results unchanged")
    history = history_path(report)
    require(not git(root, "ls-tree", "HEAD", "--", history), "history already exists")
    encoded = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    updates = {"results/latest.json": encoded, history: encoded}
    for filename, locale in (("README.md", "en"), ("README.ja.md", "ja")):
        original = read_regular(root / filename, root).decode("utf-8")
        updates[filename] = replace_section(original, render(report, locale)).encode()
    with tempfile.TemporaryDirectory(prefix="sab-publish-") as directory:
        env = dict(os.environ if environment is None else environment)
        env.update(
            GIT_INDEX_FILE=str(Path(directory) / "index"),
            GIT_AUTHOR_NAME="github-actions[bot]",
            GIT_COMMITTER_NAME="github-actions[bot]",
            GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
            GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
        )
        git(root, "read-tree", source, environment=env)
        for filename, content in updates.items():
            blob = git(root, "hash-object", "-w", "--stdin", data=content, environment=env)
            git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                "100644",
                blob,
                filename,
                environment=env,
            )
        tree = git(root, "write-tree", environment=env)
        commit = git(
            root,
            "commit-tree",
            tree,
            "-p",
            source,
            data=b"chore: publish verified benchmark results [skip ci]\n",
            environment=env,
        )
        changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        require(set(changed) == set(updates), "publication must update exactly four result files")
        # The remote ref update is the only publication commit point. A concurrent main
        # update makes this ordinary push non-fast-forward; it is never rebased or forced.
        git(root, "push", "origin", f"{commit}:refs/heads/main", environment=env)
    print(f"Published verified results atomically: {commit}")
    return commit


def main() -> int:
    try:
        context = trusted_context()
        token = os.environ.get("GH_TOKEN")
        require(bool(token), "publishing token required")
        require(
            git(ROOT, "remote", "get-url", "origin")
            in (f"https://github.com/{REPOSITORY}", f"https://github.com/{REPOSITORY}.git"),
            "unexpected publication remote",
        )
        # Environment-only Git config; no credential in .git/config or command arguments.
        environment = dict(os.environ)
        authorization = base64.b64encode(("x-access-token:" + token).encode()).decode()
        environment.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + authorization,
        )
        report = strict_json(read_regular(ROOT / ".cache/official/selected.json", ROOT))
        publish(report, ROOT, expected_context=context, environment=environment)
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Result publication failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
