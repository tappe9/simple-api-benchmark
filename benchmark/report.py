"""Validate complete official reports and audit them against the retained raw data."""

import re
from datetime import datetime, timezone
from pathlib import Path

from . import registry
from .contract_test import load_cases
from .definition import PROFILE
from .healthcheck import CONTAINER_HEALTHCHECK, validate_policy
from .results import (
    number,
    object_fields,
    parse_oha,
    require,
    select_run,
    strict_json,
    validate_run,
)

REPOSITORY = "tappe9/simple-api-benchmark"
REF = "refs/heads/main"
WORKFLOW = REPOSITORY + "/.github/workflows/benchmark.yml@" + REF


def timestamp(value: str) -> datetime:
    require(type(value) is str, "expected UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        require(False, "invalid UTC timestamp")
    require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, "expected UTC")
    return result.astimezone(timezone.utc)


def text(value, label: str) -> str:
    require(type(value) is str and bool(value.strip()) and len(value) <= 4096, label)
    return value


def sha(value, label: str) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None, label)
    return value


def api_health_policy(report: dict) -> str:
    """Resolve measurement health policy without reinterpreting legacy results."""
    require(type(report) is dict, "report must be an object")
    schema_version = report.get("schema_version")
    require(schema_version in (1, 2), "unsupported report schema")
    metadata = report.get("metadata")
    require(type(metadata) is dict, "metadata required")
    value = metadata.get("api_health_policy")
    if schema_version == 1:
        if value is None:
            return CONTAINER_HEALTHCHECK
        policy = validate_policy(value)
        require(
            policy == CONTAINER_HEALTHCHECK,
            "schema-v1 cannot claim a post-legacy API health policy",
        )
        return policy
    require(value is not None, "schema-v2 API health policy provenance required")
    return validate_policy(value)


def comparison_compatibility(report: dict) -> tuple:
    """Return a stable key for result sets that may be compared as one methodology."""
    members = registry.report_members(report)
    conditions = object_fields(report.get("conditions"), PROFILE, "conditions")
    schema_version = report["schema_version"]
    if schema_version == 1:
        benchmark_identity = ("simple-api-v1", registry.LEGACY_COHORT)
    else:
        benchmark = object_fields(report.get("benchmark"), ("definition", "cohort"), "benchmark")
        benchmark_identity = (benchmark["definition"], benchmark["cohort"])
    condition_identity = tuple(
        (
            field,
            tuple(conditions[field]) if type(conditions[field]) is list else conditions[field],
        )
        for field in PROFILE
    )
    return (
        benchmark_identity,
        tuple(members),
        condition_identity,
        api_health_policy(report),
    )


def validate_context(context: dict) -> None:
    object_fields(
        context,
        (
            "repository",
            "ref",
            "source_commit",
            "event",
            "workflow_ref",
            "workflow_sha",
            "run_id",
            "run_attempt",
            "run_url",
        ),
        "GitHub provenance",
    )
    require(context["repository"] == REPOSITORY and context["ref"] == REF, "untrusted source ref")
    require(context["event"] in ("schedule", "workflow_dispatch"), "untrusted event")
    require(context["workflow_ref"] == WORKFLOW, "untrusted workflow ref")
    sha(context["source_commit"], "invalid source commit")
    require(context["workflow_sha"] == context["source_commit"], "workflow/source mismatch")
    for key in ("run_id", "run_attempt"):
        require(
            type(context[key]) is str and re.fullmatch(r"[1-9][0-9]*", context[key]) is not None,
            "invalid " + key,
        )
    require(
        context["run_url"] == f"https://github.com/{REPOSITORY}/actions/runs/{context['run_id']}",
        "invalid run URL",
    )


def validate_report(report: dict, *, expected_context: dict | None = None) -> None:
    members = registry.report_members(report)
    object_fields(
        report,
        (
            "schema_version",
            "status",
            "mode",
            "official",
            "started_at",
            "completed_at",
            "conditions",
            "metadata",
            "implementations",
            *(("benchmark",) if report["schema_version"] == 2 else ()),
        ),
        "report",
    )
    require(report["official"] is True and report["mode"] == "official", "not an official result")
    require(report["status"] == "verified", "unverified result")
    conditions = object_fields(report["conditions"], PROFILE, "conditions")
    for field, expected in PROFILE.items():
        require(
            type(conditions[field]) is type(expected) and conditions[field] == expected,
            "nonstandard condition: " + field,
        )
    require(timestamp(report["completed_at"]) >= timestamp(report["started_at"]), "time order")
    metadata = report["metadata"]
    require(type(metadata) is dict, "metadata required")
    api_health_policy(report)
    sha(metadata.get("source_commit"), "source commit missing")
    sha(metadata.get("source_tree"), "source tree missing")
    validate_context(metadata.get("github"))
    require(metadata["github"]["source_commit"] == metadata["source_commit"], "provenance mismatch")
    if expected_context is not None:
        validate_context(expected_context)
        require(metadata["github"] == expected_context, "artifact belongs to a different run")
    runner = object_fields(
        metadata.get("runner"),
        (
            "name",
            "environment",
            "os",
            "architecture",
            "image_os",
            "image_version",
            "cpu_model",
        ),
        "runner",
    )
    for key, value in runner.items():
        text(value, "missing runner " + key)
    require(runner["environment"] == "github-hosted" and runner["os"] == "Linux", "runner type")
    require(type(metadata.get("docker")) is dict, "Docker metadata required")
    text(metadata["docker"].get("ServerVersion"), "Docker server version required")
    text(metadata.get("docker_cli"), "Docker CLI version required")
    text(metadata.get("docker_compose"), "Docker Compose version required")
    versions = object_fields(metadata.get("versions"), members, "versions")
    for implementation in members:
        keys = registry.implementation(implementation)["version_fields"]
        values = versions[implementation]
        require(type(values) is dict and set(keys) <= set(values), "missing stack versions")
        for value in values.values():
            require(
                type(value) is str and re.fullmatch(r"\d+\.\d+\.\d+", value) is not None,
                "invalid stack version",
            )
    backends = report["implementations"]
    require(type(backends) is list and len(backends) == len(members), "complete cohort required")
    for backend, implementation in zip(backends, members):
        object_fields(
            backend, ("implementation", "container", "contract_checks", "endpoints"), "backend"
        )
        require(backend["implementation"] == implementation, "API order/identity mismatch")
        require(
            type(backend["contract_checks"]) is int
            and backend["contract_checks"] == 2 * len(load_cases()),
            "incomplete contract",
        )
        container = object_fields(
            backend["container"], ("id", "image_id", "command", "postgresql_version"), "container"
        )
        require(
            type(container["id"]) is str and re.fullmatch(r"[0-9a-f]{64}", container["id"]),
            "container ID required",
        )
        text(container["image_id"], "image ID required")
        require(
            type(container["command"]) is list and bool(container["command"]), "command required"
        )
        for argument in container["command"]:
            text(argument, "invalid command")
        require(
            text(container["postgresql_version"], "PostgreSQL version required").startswith(
                "PostgreSQL "
            ),
            "PostgreSQL version required",
        )
        endpoints = backend["endpoints"]
        require(type(endpoints) is list and len(endpoints) == 3, "three endpoints required")
        for entry, endpoint in zip(endpoints, PROFILE["endpoints"]):
            object_fields(entry, ("endpoint", "runs", "selected"), "endpoint")
            require(entry["endpoint"] == endpoint, "endpoint order/identity mismatch")
            selected = select_run(entry["runs"])
            validate_run(entry["selected"])
            require(entry["selected"] == selected, "selected metrics are not the middle whole run")
            for run in entry["runs"]:
                require(30 <= run["elapsed_seconds"] <= 47, "full duration required")


def read_regular(path: Path, root: Path, *, limit: int = 1024 * 1024) -> bytes:
    require(path.is_relative_to(root), "path escapes artifact root")
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "symlink in result path")
        if parent == root:
            break
    require(path.is_file() and path.stat().st_size <= limit, "missing/oversized result file")
    return path.read_bytes()


def audit_raw(report: dict, root: Path) -> None:
    validate_report(report)
    relative = report["metadata"].get("artifact_directory")
    require(
        type(relative) is str
        and re.fullmatch(r"\.cache/official/raw/sab-benchmark-[a-zA-Z0-9]+", relative),
        "invalid raw directory",
    )
    directory = root / relative
    for backend in report["implementations"]:
        for endpoint in backend["endpoints"]:
            stem = (
                backend["implementation"] + "-" + endpoint["endpoint"].strip("/").replace("/", "-")
            )
            for run in endpoint["runs"]:
                path = directory / f"{stem}-run-{run['run']}.json"
                raw = parse_oha(read_regular(path, root), duration=30, request_timeout=15)
                require(all(run[key] == value for key, value in raw.items()), "raw metric mismatch")
                samples = [
                    strict_json(line)
                    for line in read_regular(path.with_suffix(".memory.jsonl"), root).splitlines()
                ]
                require(len(samples) == run["memory_samples"] and bool(samples), "sample count")
                previous = timestamp(report["started_at"])
                for sample in samples:
                    object_fields(sample, ("at", "bytes", "container_id"), "memory sample")
                    require(
                        sample["container_id"] == backend["container"]["id"], "wrong API memory"
                    )
                    number(sample["bytes"], "sample bytes", integer=True, positive=True)
                    require(sample["bytes"] <= PROFILE["api_memory_bytes"], "memory exceeds limit")
                    current = timestamp(sample["at"])
                    require(previous <= current <= timestamp(report["completed_at"]), "sample time")
                    previous = current
                require(
                    max(s["bytes"] for s in samples) == run["peak_memory_bytes"], "peak mismatch"
                )
