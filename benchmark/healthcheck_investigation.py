"""Run a diagnostic-only same-runner A/B investigation of API health probes."""

import argparse
import copy
import math
import re
import sys
from pathlib import Path

from .contract_test import ContractFailure, load_cases, run_contract
from .definition import PROFILE
from .healthcheck import CONTAINER_HEALTHCHECK, EXTERNAL_READINESS
from .registry import active_benchmark, active_members
from .results import BenchmarkFailure, atomic_json, object_fields, require, select_run, validate_run

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache" / "healthcheck-investigation"
_MEASUREMENT_FIELDS = (
    "run",
    "requests_per_second",
    "mean_response_time_ms",
    "peak_memory_bytes",
    "memory_samples",
    "elapsed_seconds",
    "successful_requests",
    "response_bytes",
)
_EVENT_FIELDS = (
    "total_execs",
    "probe_execs",
    "non_probe_execs",
    "probe_start_timestamps_ns",
)
_METRICS = ("requests_per_second", "mean_response_time_ms", "peak_memory_bytes")


def split_observation(summary: dict) -> dict:
    """Keep strict benchmark measurement fields separate from diagnostic event evidence."""
    object_fields(summary, (*_MEASUREMENT_FIELDS, "health_probe_events"), "investigation run")
    measurement = {field: summary[field] for field in _MEASUREMENT_FIELDS}
    validate_run(measurement)
    events = object_fields(summary["health_probe_events"], _EVENT_FIELDS, "health probe events")
    for field in ("total_execs", "probe_execs", "non_probe_execs"):
        require(
            type(events[field]) is int and not isinstance(events[field], bool) and events[field] >= 0,
            "invalid health probe event count",
        )
    require(
        events["total_execs"] == events["probe_execs"] + events["non_probe_execs"],
        "inconsistent health probe event counts",
    )
    timestamps = events["probe_start_timestamps_ns"]
    require(
        type(timestamps) is list
        and len(timestamps) == events["probe_execs"]
        and all(type(value) is int and value > 0 for value in timestamps)
        and timestamps == sorted(timestamps),
        "invalid health probe event timestamps",
    )
    return {"measurement": measurement, "health_probe_events": copy.deepcopy(events)}


def metric_comparison(
    baseline_values: list[float | int],
    controlled_values: list[float | int],
    baseline_selected: float | int,
    controlled_selected: float | int,
) -> dict:
    """Describe three paired observations without inferential statistics."""
    require(
        type(baseline_values) is list
        and type(controlled_values) is list
        and len(baseline_values) == len(controlled_values) == 3,
        "exactly three paired values are required",
    )
    all_values = [*baseline_values, *controlled_values, baseline_selected, controlled_selected]
    require(
        all(type(value) in (int, float) and not isinstance(value, bool) for value in all_values),
        "comparison values must be numeric",
    )
    require(
        all((math.isfinite(value) if type(value) is float else True) and value >= 0 for value in all_values),
        "comparison values must be finite and nonnegative",
    )
    delta = controlled_selected - baseline_selected
    directions = {"higher": 0, "equal": 0, "lower": 0}
    for baseline, controlled in zip(baseline_values, controlled_values):
        if controlled > baseline:
            directions["higher"] += 1
        elif controlled < baseline:
            directions["lower"] += 1
        else:
            directions["equal"] += 1
    return {
        "baseline_selected": baseline_selected,
        "controlled_selected": controlled_selected,
        "selected_absolute_delta": delta,
        "selected_percent_delta": None if baseline_selected == 0 else delta / baseline_selected * 100,
        "baseline_range": [min(baseline_values), max(baseline_values)],
        "controlled_range": [min(controlled_values), max(controlled_values)],
        "paired_direction": directions,
    }


def _policy_endpoints(value: dict, expected_policy: str) -> list[dict]:
    require(type(value) is dict and value.get("policy") == expected_policy, "unexpected policy observation")
    endpoints = value.get("endpoints")
    require(type(endpoints) is list and bool(endpoints), "policy endpoints are required")
    return endpoints


def analyze_pair(baseline: dict, controlled: dict) -> dict:
    """Compare baseline and controlled observations without a significance claim."""
    baseline_endpoints = _policy_endpoints(baseline, CONTAINER_HEALTHCHECK)
    controlled_endpoints = _policy_endpoints(controlled, EXTERNAL_READINESS)
    require(
        len(baseline_endpoints) == len(controlled_endpoints),
        "policy endpoint counts differ",
    )
    result = []
    for baseline_endpoint, controlled_endpoint in zip(baseline_endpoints, controlled_endpoints):
        endpoint = baseline_endpoint.get("endpoint")
        require(
            type(endpoint) is str
            and controlled_endpoint.get("endpoint") == endpoint,
            "policy endpoint identities differ",
        )
        baseline_runs = baseline_endpoint.get("runs")
        controlled_runs = controlled_endpoint.get("runs")
        require(
            type(baseline_runs) is list
            and type(controlled_runs) is list
            and len(baseline_runs) == len(controlled_runs) == 3,
            "exactly three policy runs are required",
        )
        for observed in [*baseline_runs, *controlled_runs]:
            object_fields(observed, ("measurement", "health_probe_events"), "observed run")
            validate_run(observed["measurement"])
        baseline_measurements = [observed["measurement"] for observed in baseline_runs]
        controlled_measurements = [observed["measurement"] for observed in controlled_runs]
        baseline_selected = select_run(baseline_measurements)
        controlled_selected = select_run(controlled_measurements)
        require(
            baseline_endpoint.get("selected") == baseline_selected
            and controlled_endpoint.get("selected") == controlled_selected,
            "stored selected run does not match the existing selection rule",
        )
        metrics = {}
        for metric in _METRICS:
            metrics[metric] = metric_comparison(
                [run[metric] for run in baseline_measurements],
                [run[metric] for run in controlled_measurements],
                baseline_selected[metric],
                controlled_selected[metric],
            )
        result.append({"endpoint": endpoint, "metrics": metrics})
    return {"endpoints": result}


def _readiness(policy: str, value) -> dict:
    require(type(value) is dict, "readiness evidence is required")
    attempts = value.get("attempts")
    duration = value.get("duration_seconds")
    require(type(attempts) is int and not isinstance(attempts, bool) and attempts > 0, "readiness attempts are required")
    require(
        type(duration) in (int, float)
        and not isinstance(duration, bool)
        and math.isfinite(duration)
        and duration >= 0,
        "readiness duration is required",
    )
    return {
        "mechanism": policy,
        "attempts": attempts,
        "duration_seconds": duration,
    }


def _collect_policy(implementation_id: str, policy: str, config: dict, environment, contract) -> dict:
    environment.build(implementation_id)
    container = environment.start(implementation_id)
    checks = contract("http://127.0.0.1:8080", implementation=implementation_id)
    require(
        type(checks) is int and checks == 2 * len(load_cases()),
        "shared contract did not complete both rounds",
    )
    environment.check()
    endpoints = []
    for endpoint in config["endpoints"]:
        warmup = split_observation(environment.measure(endpoint, config["warmup_seconds"], 0))
        runs = [
            split_observation(environment.measure(endpoint, config["duration_seconds"], index))
            for index in (1, 2, 3)
        ]
        measurements = [observed["measurement"] for observed in runs]
        endpoints.append(
            {
                "endpoint": endpoint,
                "warmup": {"health_probe_events": warmup["health_probe_events"]},
                "runs": runs,
                "selected": select_run(measurements),
            }
        )
    environment.check()
    return {
        "policy": policy,
        "readiness": _readiness(policy, environment.readiness),
        "container": container,
        "contract_checks": checks,
        "endpoints": endpoints,
    }


def collect_investigation(*, config: dict, metadata: dict, environment_factory, contract=run_contract, now) -> dict:
    """Collect both policies sequentially; callers write only after complete success."""
    object_fields(config, PROFILE, "investigation config")
    for field, expected in PROFILE.items():
        require(
            type(config[field]) is type(expected) and config[field] == expected,
            "investigation requires unchanged full benchmark profile: " + field,
        )
    require(type(metadata) is dict, "investigation metadata required")
    for field in ("source_commit", "source_tree"):
        require(
            type(metadata.get(field)) is str and re.fullmatch(r"[0-9a-f]{40}", metadata[field]),
            "investigation metadata missing " + field,
        )
    started_at = now()
    implementations = []
    analyses = []
    for index, implementation_id in enumerate(active_members()):
        policy_order = (
            [CONTAINER_HEALTHCHECK, EXTERNAL_READINESS]
            if index % 2 == 0
            else [EXTERNAL_READINESS, CONTAINER_HEALTHCHECK]
        )
        policies = []
        for policy in policy_order:
            environment = environment_factory(implementation_id, policy)
            try:
                policies.append(_collect_policy(implementation_id, policy, config, environment, contract))
            finally:
                environment.cleanup()
        by_policy = {value["policy"]: value for value in policies}
        require(set(by_policy) == {CONTAINER_HEALTHCHECK, EXTERNAL_READINESS}, "both policies are required")
        analysis = analyze_pair(
            by_policy[CONTAINER_HEALTHCHECK],
            by_policy[EXTERNAL_READINESS],
        )
        implementations.append(
            {
                "implementation": implementation_id,
                "policy_order": policy_order,
                "policies": policies,
            }
        )
        analyses.append({"implementation": implementation_id, **analysis})
    completed_at = now()
    return {
        "schema_version": 1,
        "status": "verified",
        "mode": "healthcheck-investigation",
        "official": False,
        "publishable": False,
        "started_at": started_at,
        "completed_at": completed_at,
        "benchmark": active_benchmark(),
        "conditions": copy.deepcopy(config),
        "metadata": copy.deepcopy(metadata),
        "policy_definitions": {
            CONTAINER_HEALTHCHECK: "Recurring API Compose healthcheck remains enabled during measurement.",
            EXTERNAL_READINESS: "API Compose healthcheck is disabled after bounded host-side readiness completes.",
        },
        "implementations": implementations,
        "analysis": analyses,
    }


def validate_output_path(path: Path, *, cache_root: Path = CACHE_ROOT) -> Path:
    """Restrict diagnostics to the dedicated cache tree and reject symlink traversal."""
    require(type(path) is Path and type(cache_root) is Path, "diagnostic output paths must be Path values")
    root = cache_root.resolve(strict=False)
    candidate = path.resolve(strict=False)
    require(candidate.is_relative_to(root), "diagnostic output must stay below healthcheck cache root")
    current = path
    while current != cache_root.parent:
        if current.exists() or current.is_symlink():
            require(not current.is_symlink(), "symlink in diagnostic output path")
        if current == cache_root:
            break
        current = current.parent
    return candidate


def write_diagnostic(path: Path, value: dict) -> Path:
    target = validate_output_path(path)
    atomic_json(target, value)
    return target


def main(argv: list[str] | None = None) -> int:
    from .environment import DockerEnvironment, provenance
    from .install_oha import ensure_oha
    from .run import load_config, now

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=CACHE_ROOT / "result.json",
        help="diagnostic JSON path below .cache/healthcheck-investigation/",
    )
    args = parser.parse_args(argv)
    try:
        output = validate_output_path(args.output)
        config = load_config()
        oha = ensure_oha()
        metadata = provenance(oha)
        raw_root = CACHE_ROOT / "raw"

        def factory(implementation_id: str, policy: str):
            return DockerEnvironment(
                oha,
                raw_root / implementation_id / policy,
                connections=config["connections"],
                request_timeout=config["request_timeout_seconds"],
                health_policy=policy,
                audit_health_events=True,
            )

        value = collect_investigation(
            config=config,
            metadata=metadata,
            environment_factory=factory,
            contract=run_contract,
            now=now,
        )
        write_diagnostic(output, value)
        print(f"Healthcheck investigation saved to {output.relative_to(ROOT)}; not publishable.")
        return 0
    except (BenchmarkFailure, ContractFailure, OSError, ValueError) as error:
        print(f"Healthcheck investigation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
