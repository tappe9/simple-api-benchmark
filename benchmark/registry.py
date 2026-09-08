"""Implementation identity and versioned cohorts; no measurement orchestration.

The JSON registry is trusted source configuration, never supplied by a report.
Only this module's deterministic projections are consumed by JavaScript and Make.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from .definition import DEFINITION_ID, PROFILE
from .results import BenchmarkFailure, object_fields, require, strict_json

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "benchmark/implementations.json"
# Never resolve an untagged historical report to the current active cohort.
LEGACY_COHORT = "four-stack-v1"


def validate_registry(data: dict) -> dict:
    object_fields(
        data, ("schema_version", "active_cohort", "implementations", "cohorts"), "registry"
    )
    require(type(data["schema_version"]) is int and data["schema_version"] == 1, "registry schema")
    specs = data["implementations"]
    require(type(specs) is list and bool(specs), "implementation registry must not be empty")
    identifiers = []
    sources = []
    for spec in specs:
        object_fields(
            spec,
            (
                "id",
                "language",
                "framework",
                "display_name",
                "source_path",
                "version_fields",
                "acceptance_test",
                "failure_test",
            ),
            "implementation registration",
        )
        identifier = spec["id"]
        require(
            type(identifier) is str and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", identifier),
            "invalid implementation ID",
        )
        identifiers.append(identifier)
        for key in ("language", "framework", "display_name"):
            value = spec[key]
            require(
                type(value) is str
                and 0 < len(value.strip()) <= 128
                and all(ord(c) >= 32 for c in value),
                "invalid " + key,
            )
        path = spec["source_path"]
        require(
            type(path) is str and re.fullmatch(r"apps/[a-z][a-z0-9]*(?:-[a-z0-9]+)+", path),
            "invalid source path",
        )
        sources.append(path)
        for key in ("acceptance_test", "failure_test"):
            value = spec[key]
            if key == "failure_test" and value is None:
                continue
            require(
                type(value) is str and re.fullmatch(r"tests/test_[a-z0-9_]+\.py", value),
                "invalid test path",
            )
        fields = spec["version_fields"]
        require(type(fields) is list and bool(fields), "required version fields missing")
        require(
            all(type(key) is str and re.fullmatch(r"[a-z][a-z0-9_-]*", key) for key in fields),
            "invalid version field",
        )
        require(len(fields) == len(set(fields)), "duplicate version fields")
    require(len(identifiers) == len(set(identifiers)), "duplicate implementation ID")
    require(len(sources) == len(set(sources)), "implementations must have independent source paths")
    cohorts = data["cohorts"]
    require(
        type(cohorts) is dict and LEGACY_COHORT in cohorts, "legacy cohort must remain registered"
    )
    for identifier, cohort in cohorts.items():
        require(
            type(identifier) is str and re.fullmatch(r"[a-z][a-z0-9-]*-v[1-9][0-9]*", identifier),
            "cohort ID must be versioned",
        )
        object_fields(cohort, ("definition", "members"), "cohort")
        require(cohort["definition"] == DEFINITION_ID, "unknown benchmark definition")
        members = cohort["members"]
        require(type(members) is list and bool(members), "cohort must have members")
        require(
            all(type(member) is str and member in identifiers for member in members),
            "unknown cohort member",
        )
        require(len(members) == len(set(members)), "duplicate cohort member")
    require(
        type(data["active_cohort"]) is str and data["active_cohort"] in cohorts,
        "unknown active cohort",
    )
    return data


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return validate_registry(strict_json(path.read_bytes()))


REGISTRY = load_registry()


def implementation_ids() -> tuple[str, ...]:
    return tuple(spec["id"] for spec in REGISTRY["implementations"])


def implementation(identifier: str) -> dict:
    for spec in REGISTRY["implementations"]:
        if spec["id"] == identifier:
            return spec
    raise BenchmarkFailure("unknown implementation ID")


def active_members() -> tuple[str, ...]:
    return tuple(REGISTRY["cohorts"][REGISTRY["active_cohort"]]["members"])


def active_benchmark() -> dict:
    return {"definition": DEFINITION_ID, "cohort": REGISTRY["active_cohort"]}


def report_members(report: dict) -> tuple[str, ...]:
    require(type(report) is dict, "report must be an object")
    version = report.get("schema_version")
    require(type(version) is int and version in (1, 2), "unsupported report schema")
    if version == 1:
        require("benchmark" not in report, "schema-v1 uses only the frozen legacy cohort")
        cohort_id = LEGACY_COHORT
    else:
        identity = object_fields(
            report.get("benchmark"), ("definition", "cohort"), "benchmark identity"
        )
        cohort_id = identity["cohort"]
        require(
            type(cohort_id) is str and cohort_id in REGISTRY["cohorts"], "unknown benchmark cohort"
        )
        require(
            identity["definition"] == REGISTRY["cohorts"][cohort_id]["definition"] == DEFINITION_ID,
            "unknown benchmark definition/cohort pairing",
        )
    return tuple(REGISTRY["cohorts"][cohort_id]["members"])


def generated_files() -> dict[str, str]:
    validate_registry(REGISTRY)
    projection = {
        "legacy_cohort": LEGACY_COHORT,
        "definition": {"id": DEFINITION_ID, "conditions": PROFILE},
        "cohorts": REGISTRY["cohorts"],
        "implementations": [
            {
                key: value
                for key, value in spec.items()
                if key not in ("acceptance_test", "failure_test")
            }
            for spec in REGISTRY["implementations"]
        ],
    }
    javascript = "// Generated by python -m benchmark.registry --write; do not edit.\n"
    javascript += (
        "export const REGISTRY = "
        + json.dumps(projection, ensure_ascii=True, allow_nan=False, sort_keys=True, indent=2)
        + ";\n"
    )
    targets = ["test-" + identifier for identifier in implementation_ids()]
    make = [
        "# Generated by python -m benchmark.registry --write; do not edit.",
        "IMPLEMENTATION_TARGETS := " + " ".join(targets),
        ".PHONY: $(IMPLEMENTATION_TARGETS)",
        "",
    ]
    for spec, target in zip(REGISTRY["implementations"], targets):
        make.append(target + ":")
        if spec["failure_test"] is not None:
            make.append(
                "\t@$(PYTHON) -m unittest discover -s tests -p " + Path(spec["failure_test"]).name
            )
        make += ["\t@$(PYTHON) " + spec["acceptance_test"], ""]
    return {"site/registry.mjs": javascript, "benchmark/implementations.mk": "\n".join(make)}


def require_scoped_path(path: Path, root: Path) -> None:
    require(path.is_relative_to(root), "registry path escapes repository root")
    require(
        not any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root)),
        "symlinked registry path: " + str(path),
    )


def check_generated(root: Path = ROOT) -> None:
    for name, expected in generated_files().items():
        path = root / name
        require_scoped_path(path, root)
        require(path.is_file(), "missing generated projection: " + name)
        require(
            path.read_bytes() == expected.encode("utf-8"), "stale generated projection: " + name
        )


def check_sources(root: Path = ROOT) -> None:
    validate_registry(REGISTRY)
    for spec in REGISTRY["implementations"]:
        paths = [spec["source_path"] + "/Dockerfile", spec["acceptance_test"]]
        if spec["failure_test"] is not None:
            paths.append(spec["failure_test"])
        for relative in paths:
            path = root / relative
            require_scoped_path(path, root)
            require(path.is_file(), "missing implementation input: " + relative)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify sources and deterministic projections (default)",
    )
    mode.add_argument(
        "--write", action="store_true", help="regenerate only the Make and JavaScript projections"
    )
    args = parser.parse_args(argv)
    try:
        check_sources(ROOT)
        if args.write:
            outputs = generated_files()
            for name in outputs:
                require_scoped_path(ROOT / name, ROOT)
            for name, content in outputs.items():
                (ROOT / name).write_text(content, encoding="utf-8")
        else:
            check_generated(ROOT)
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"Registry validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
