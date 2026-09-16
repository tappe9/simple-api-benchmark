"""Publish verified results and generated presentation assets in one fast-forward Git update."""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .generate_readme import render, replace_section
from .official import trusted_context
from .publication import CHART_PUBLICATION_PATHS, expected_publication_paths, history_path
from .publication_candidate import PublicationCandidate
from .readme_charts import render_charts
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


def prepare_publication(
    report: dict,
    root: Path,
    *,
    expected_context: dict,
    for_pr: bool = False,
    environment=None,
) -> PublicationCandidate:
    """Audit and create Git objects only; never update a ref, index, worktree or remote.

    PR candidates use stable dates and a CI-enabled message. Rebuilding the same
    trusted source/report yields the same identity for lost-response reconciliation.
    Remote freshness remains a separate check at the actual publication boundary.
    """
    require(type(for_pr) is bool, "invalid publication candidate mode")
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
    history = history_path(report)
    require(not git(root, "ls-tree", "HEAD", "--", history), "history already exists")
    encoded = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    updates = {"results/latest.json": encoded, history: encoded}
    for filename, locale in (("README.md", "en"), ("README.ja.md", "ja")):
        original = read_regular(root / filename, root).decode("utf-8")
        updates[filename] = replace_section(original, render(report, locale)).encode()
    charts = render_charts(report)
    require(set(charts) == CHART_PUBLICATION_PATHS, "unexpected README chart output")
    updates.update({path: svg.encode("utf-8") for path, svg in charts.items()})
    allowed = expected_publication_paths(report)
    require(set(updates) == allowed, "unexpected publication path")
    with tempfile.TemporaryDirectory(prefix="sab-publish-") as directory:
        env = dict(os.environ if environment is None else environment)
        env.update(
            GIT_INDEX_FILE=str(Path(directory) / "index"),
            GIT_AUTHOR_NAME="github-actions[bot]",
            GIT_COMMITTER_NAME="github-actions[bot]",
            GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
            GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
        )
        if for_pr:
            # A fixed UTC date is independent of runner wall time and ambient Git dates.
            date = str(int(timestamp(report["completed_at"]).timestamp())) + " +0000"
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
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
            data=(
                b"chore: propose verified benchmark results\n"
                if for_pr
                else b"chore: publish verified benchmark results [skip ci]\n"
            ),
            environment=env,
        )
        changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        require(set(changed) == allowed, "publication changed an unexpected path")
    return PublicationCandidate(
        source=source,
        source_tree=report["metadata"]["source_tree"],
        commit=commit,
        tree=tree,
        run_id=expected_context["run_id"],
        run_attempt=expected_context["run_attempt"],
        report_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def verify_candidate(
    candidate: PublicationCandidate,
    report: dict,
    root: Path,
    *,
    expected_context: dict,
) -> None:
    """Do not authenticate a proposed transaction from serialized metadata alone."""
    rebuilt = prepare_publication(report, root, expected_context=expected_context, for_pr=True)
    require(candidate == rebuilt, "publication candidate differs from audited source/evidence")


def publish(report: dict, root: Path, *, expected_context: dict, environment=None) -> str:
    candidate = prepare_publication(
        report, root, expected_context=expected_context, environment=environment
    )
    remote = git(
        root, "ls-remote", "--exit-code", "origin", "refs/heads/main", environment=environment
    )
    require(
        remote.split()[0] == candidate.source, "main advanced; leave verified results unchanged"
    )
    # This ordinary push is still the only publication commit point. A concurrent
    # main update is non-fast-forward; never rebase, force, or fall back to another ref.
    git(root, "push", "origin", f"{candidate.commit}:refs/heads/main", environment=environment)
    print(f"Published verified results atomically: {candidate.commit}")
    return candidate.commit


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
        output = Path(os.environ.get("GITHUB_OUTPUT", ""))
        require(output.is_file() and not output.is_symlink(), "publishing output file required")
        commit = publish(report, ROOT, expected_context=context, environment=environment)
        require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "invalid publication SHA")
        # These outputs are emitted only after the audited fast-forward push succeeds.
        # A failed output write does not undo publication: recover Pages, not measurement.
        try:
            with output.open("a", encoding="utf-8") as stream:
                stream.write(
                    f"publication_sha={commit}\nsource_sha={context['source_commit']}\n"
                    f"producer_run_id={context['run_id']}\n"
                    f"producer_run_attempt={context['run_attempt']}\n"
                )
        except OSError as error:
            raise BenchmarkFailure(
                "results published, but Pages outputs failed; use Pages recovery"
            ) from error
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Result publication failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
