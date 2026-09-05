"""Build the static Pages artifact from trusted source assets and a verified result."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from .report import validate_report
from .results import BenchmarkFailure, require, strict_json

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("index.html", "style.css", "app.mjs")


def regular_file(path: Path, root: Path) -> bytes:
    require(path.is_relative_to(root), "site input escapes repository root")
    require(not path.is_symlink(), f"site input must not be a symlink: {path.name}")
    require(path.is_file(), f"missing site input: {path.name}")
    return path.read_bytes()


def build(root: Path = ROOT) -> Path:
    root = root.resolve()
    site = root / "site"
    results = root / "results" / "latest.json"
    output = root / ".cache" / "site"

    assets = {name: regular_file(site / name, root) for name in ASSETS}
    result_bytes = None
    if results.exists() or results.is_symlink():
        result_bytes = regular_file(results, root)
        report = strict_json(result_bytes)
        validate_report(report)

    cache = output.parent
    cache.mkdir(parents=True, exist_ok=True)
    require(not output.is_symlink(), "site output must not be a symlink")

    stage = Path(tempfile.mkdtemp(prefix="site-stage-", dir=cache))
    backup = None
    try:
        for name, content in assets.items():
            (stage / name).write_bytes(content)
        (stage / ".nojekyll").write_bytes(b"")
        if result_bytes is not None:
            destination = stage / "results"
            destination.mkdir()
            (destination / "latest.json").write_bytes(result_bytes)

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
