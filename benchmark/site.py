"""Build the static Pages artifact from trusted source assets and verified results."""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .registry import generated_files
from .report import validate_report
from .results import BenchmarkFailure, require, strict_json

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("index.html", "style.css", "app.mjs", "registry.mjs")
HISTORY_NAME = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)-"
    r"(?P<run_id>[1-9][0-9]*)-(?P<run_attempt>[1-9][0-9]*)\.json$"
)
MAX_HISTORY_FILES = 128
MAX_HISTORY_FILE_BYTES = 1024 * 1024
MAX_HISTORY_TOTAL_BYTES = 16 * 1024 * 1024


def regular_file(path: Path, root: Path) -> bytes:
    require(path.is_relative_to(root), "site input escapes repository root")
    require(not path.is_symlink(), f"site input must not be a symlink: {path.name}")
    require(path.is_file(), f"missing site input: {path.name}")
    return path.read_bytes()


def history_files(root: Path) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    history = root / "results" / "history"
    if not history.exists() and not history.is_symlink():
        return [], {}
    require(not history.is_symlink(), "history input must not be a symlink")
    require(history.is_dir(), "history input must be a directory")

    children = sorted(history.iterdir(), key=lambda path: path.name)
    require(len(children) <= MAX_HISTORY_FILES, "too many history files")
    entries: list[dict[str, str]] = []
    contents: dict[str, bytes] = {}
    identities: set[str] = set()
    total_bytes = 0

    for path in children:
        require(not path.is_symlink(), f"history input must not be a symlink: {path.name}")
        require(path.is_file(), f"unexpected history entry: {path.name}")
        match = HISTORY_NAME.fullmatch(path.name)
        require(match is not None, f"unexpected history filename: {path.name}")
        size = path.stat().st_size
        require(size <= MAX_HISTORY_FILE_BYTES, f"history file is too large: {path.name}")
        total_bytes += size
        require(total_bytes <= MAX_HISTORY_TOTAL_BYTES, "history files exceed total size limit")

        raw = regular_file(path, root)
        report = strict_json(raw)
        validate_report(report)
        github = report["metadata"]["github"]
        run_id = str(github["run_id"])
        run_attempt = str(github["run_attempt"])
        require(
            run_id == match.group("run_id") and run_attempt == match.group("run_attempt"),
            f"history filename does not match run identity: {path.name}",
        )
        identity = f"{run_id}-{run_attempt}"
        require(identity not in identities, f"duplicate history run identity: {identity}")
        identities.add(identity)
        entries.append(
            {
                "id": identity,
                "completed_at": report["completed_at"],
                "path": f"./results/history/{path.name}",
            }
        )
        contents[path.name] = raw

    entries.sort(key=lambda entry: (entry["completed_at"], entry["id"]), reverse=True)
    return entries, contents


def build(root: Path = ROOT) -> Path:
    root = root.resolve()
    site = root / "site"
    results = root / "results" / "latest.json"
    output = root / ".cache" / "site"

    assets = {name: regular_file(site / name, root) for name in ASSETS}
    require(
        assets["registry.mjs"] == generated_files()["site/registry.mjs"].encode("utf-8"),
        "stale site registry projection",
    )
    result_bytes = None
    if results.exists() or results.is_symlink():
        result_bytes = regular_file(results, root)
        report = strict_json(result_bytes)
        validate_report(report)

    history_entries, history_contents = history_files(root)
    history_index = (
        json.dumps(
            {"schema_version": 1, "runs": history_entries},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    cache = output.parent
    cache.mkdir(parents=True, exist_ok=True)
    require(not output.is_symlink(), "site output must not be a symlink")

    stage = Path(tempfile.mkdtemp(prefix="site-stage-", dir=cache))
    backup = None
    try:
        for name, content in assets.items():
            (stage / name).write_bytes(content)
        (stage / ".nojekyll").write_bytes(b"")
        destination = stage / "results"
        history_destination = destination / "history"
        history_destination.mkdir(parents=True)
        if result_bytes is not None:
            (destination / "latest.json").write_bytes(result_bytes)
        for name, content in history_contents.items():
            (history_destination / name).write_bytes(content)
        (history_destination / "index.json").write_bytes(history_index)

        if output.exists():
            require(output.is_dir(), "site output must be a directory")
            backup = Path(tempfile.mkdtemp(prefix="site-backup-", dir=cache))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(stage, output)
        except BaseException:
            if backup is not None and backup.exists() and not output.exists():
                os.replace(backup, output)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
        return output
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup is not None and backup.exists() and output.exists():
            shutil.rmtree(backup)


def main() -> int:
    try:
        output = build()
        print(f"Built verified Pages artifact: {output.relative_to(ROOT)}")
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Pages site build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
