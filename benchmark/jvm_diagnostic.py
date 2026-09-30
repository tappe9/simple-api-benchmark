"""One fixed, non-publishing study of the five-second warm-up budget."""

import argparse
import copy
import hashlib
import os
import re
import signal
import sys
import uuid
from pathlib import Path
from statistics import median

from .contract_runner import protect_cleanup
from .contract_test import load_cases, run_contract
from .definition import PROFILE
from .healthcheck import EXTERNAL_READINESS
from .results import atomic_json, number, require
from .run import now

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache" / "jvm-diagnostic"
MEMBERS = ("java-spring-boot", "node-fastify", "go-gin")
ORDERS = tuple(MEMBERS[i:] + MEMBERS[:i] for i in range(3))
RULES = {
    "late_rps_range_over_median_max": 0.05,
    "late_p95_range_over_median_max": 0.10,
    "first_rps_relative_difference_max": 0.05,
    "reject_strict_monotonic_late_trend": True,
    "all_three_repeats_required": True,
}


def validate_directory(path: Path) -> Path:
    candidate = path.absolute()
    root = CACHE_ROOT.absolute()
    require(
        candidate != root and candidate.is_relative_to(root),
        "output must be below diagnostic cache",
    )
    require(candidate.resolve().is_relative_to(root.resolve()), "output escapes diagnostic cache")
    require(".." not in candidate.parts, "parent traversal in diagnostic path")
    for component in (candidate, *candidate.parents):
        require(not component.is_symlink(), "symlink in diagnostic output path")
    require(not candidate.exists(), "diagnostic attempt already exists; never overwrite or resume")
    return candidate


def analyze_windows(windows: list[dict]) -> dict:
    require(len(windows) == 4, "exactly four consecutive windows required")
    values = {}
    for field in ("requests_per_second", "p95_response_time_ms"):
        values[field] = [number(w[field], field, positive=True) for w in windows]
    rps = values["requests_per_second"]
    p95 = values["p95_response_time_ms"]

    def spread(series):
        return (max(series[1:]) - min(series[1:])) / median(series[1:])

    def trend(series):
        a, b, c = series[1:]
        return a < b < c or a > b > c

    rps_spread, latency_spread = spread(rps), spread(p95)
    late_trend = trend(rps) or trend(p95)
    stable = rps_spread <= 0.05 and latency_spread <= 0.10 and not late_trend
    difference = abs(rps[0] - median(rps[1:])) / median(rps[1:])
    return {
        "late_rps_range_over_median": rps_spread,
        "late_p95_range_over_median": latency_spread,
        "strict_monotonic_late_trend": late_trend,
        "first_rps_relative_difference": difference,
        "late_stable": stable,
        "five_second_supported": stable and difference <= 0.05,
    }


def write_checksums(directory: Path) -> None:
    entries = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "symlink in diagnostic evidence")
        if path.is_file() and path.name != "checksums.json":
            entries[str(path.relative_to(directory))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    atomic_json(directory / "checksums.json", {"algorithm": "sha256", "files": entries})


def run_study(directory: Path, factory, *, metadata: dict, contract=run_contract) -> dict:
    directory = validate_directory(directory)
    for key in ("source_commit", "source_tree"):
        require(
            type(metadata.get(key)) is str and re.fullmatch(r"[0-9a-f]{40}", metadata[key]),
            "missing source identity: " + key,
        )
    directory.mkdir(parents=True)
    conditions = copy.deepcopy(PROFILE)
    conditions.update(runs=4)
    result = {
        "schema_version": 1,
        "mode": "jvm-warmup-diagnostic",
        "official": False,
        "publishable": False,
        "status": "running",
        "started_at": now(),
        "conditions": conditions,
        "criteria": copy.deepcopy(RULES),
        "metadata": copy.deepcopy(metadata),
        "attempts": [
            {
                "round": round_index,
                "implementation": identifier,
                "status": "not-started",
                "endpoints": [],
            }
            for round_index, order in enumerate(ORDERS, 1)
            for identifier in order
        ],
    }
    output = directory / "diagnostic.json"

    def persist():
        atomic_json(output, result)

    persist()
    try:
        for index, attempt in enumerate(result["attempts"], 1):
            identifier = attempt["implementation"]
            attempt.update(status="running", started_at=now())
            persist()
            environment = None
            failure = None
            try:
                attempt_root = directory / f"{index:02d}-{identifier}"
                environment = factory(attempt_root)
                require(
                    environment.health_policy == EXTERNAL_READINESS, "external readiness required"
                )
                require(
                    environment.connections == 50 and environment.request_timeout == 15,
                    "fixed load configuration required",
                )
                attempt["artifact_directory"] = str(environment.artifacts.relative_to(directory))
                persist()
                environment.build(identifier)
                attempt["container"] = environment.start(identifier)
                attempt["readiness"] = copy.deepcopy(environment.readiness)
                checks = contract("http://127.0.0.1:8080", implementation=identifier)
                require(
                    type(checks) is int and checks == 2 * len(load_cases()),
                    "shared contract incomplete",
                )
                attempt["contract_checks"] = checks
                persist()
                environment.check()
                for endpoint in PROFILE["endpoints"]:
                    entry = {"endpoint": endpoint, "windows": []}
                    attempt["endpoints"].append(entry)
                    persist()
                    entry["warmup"] = environment.measure(endpoint, 5, 0)
                    persist()
                    for window in range(1, 5):
                        entry["windows"].append(environment.measure(endpoint, 30, window))
                        persist()
                    entry["analysis"] = analyze_windows(entry["windows"])
                    persist()
                environment.check()
            except BaseException as error:
                failure = error
                attempt.update(status="failed", error=f"{type(error).__name__}: {error}")
                persist()
                raise
            finally:
                try:
                    if environment is not None:
                        with protect_cleanup():
                            environment.cleanup()
                        attempt["cleanup"] = "passed"
                except BaseException as cleanup_error:
                    attempt.update(
                        status="failed", cleanup="failed", cleanup_error=str(cleanup_error)
                    )
                    if failure is None:
                        raise
                finally:
                    attempt["completed_at"] = now()
                    persist()
            attempt["status"] = "completed"
            persist()
        result["assessment"] = {
            identifier: {
                "five_second_supported_for_all_observed_endpoints_and_repeats": all(
                    entry["analysis"]["five_second_supported"]
                    for attempt in result["attempts"]
                    if attempt["implementation"] == identifier
                    for entry in attempt["endpoints"]
                )
            }
            for identifier in MEMBERS
        }
        result["status"] = "completed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        result["completed_at"] = now()
        persist()
        write_checksums(directory)
    return result


def main(argv=None) -> int:
    from .environment import provenance, registered_pinned_versions
    from .install_oha import ensure_oha
    from .jvm_environment import DiagnosticEnvironment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker compose")
    args = parser.parse_args(argv)
    run_directory = CACHE_ROOT / ("study-" + uuid.uuid4().hex)
    # Separate bootstrap evidence survives dependency/provenance failures before any load.
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    bootstrap = CACHE_ROOT / (run_directory.name + "-bootstrap.json")
    context = {
        "started_at": now(),
        "status": "starting",
        "official": False,
        "publishable": False,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    atomic_json(bootstrap, context)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        oha = ensure_oha()
        metadata = provenance(oha)
        versions = registered_pinned_versions()
        metadata["versions"] = {identifier: versions[identifier] for identifier in MEMBERS}
        metadata.update(
            github_run_id=context["github_run_id"],
            github_run_attempt=context["github_run_attempt"],
            jit_gc_evidence="Unavailable: production JRE unchanged; no instrumentation or extra load runs.",
        )
        run_study(
            run_directory,
            lambda root: DiagnosticEnvironment(oha, root, compose=args.compose),
            metadata=metadata,
        )
        context["status"] = "completed"
        print(f"Diagnostic completed: {run_directory}; no official results published.")
        return 0
    except (Exception, KeyboardInterrupt) as error:
        context.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(f"Diagnostic failed without retry: {error}", file=sys.stderr)
        return 1
    finally:
        context["completed_at"] = now()
        atomic_json(bootstrap, context)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
