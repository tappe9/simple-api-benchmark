"""Fixed, endpoint-isolated common warm-up screening protocol v1 (not publishable)."""

import argparse
import contextlib
import copy
import math
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
from .jvm_diagnostic import write_checksums
from .results import atomic_json, number, require
from .run import now

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache" / "common-warmup-screen"
PROTOCOL_ID = "common-warmup-screen-v1"
MEMBERS = ("java-spring-boot", "node-fastify", "go-gin")
ENDPOINTS = ("/json", "/db/42", "/cpu")
# Each consecutive group covers all three implementations and all three endpoints.
FIRST_ORDER = tuple(
    (MEMBERS[i], ENDPOINTS[(i + offset) % 3]) for offset in range(3) for i in range(3)
)
ORDERS = (FIRST_ORDER, FIRST_ORDER[::-1])
CANDIDATES = (5, 35, 65)
RULES = {
    "candidate_cumulative_load_seconds": list(CANDIDATES),
    "reference_window_indices": [6, 7, 8],
    "rps_range_over_median_max": 0.05,
    "p95_range_over_median_max": 0.10,
    "rps_relative_reference_difference_max": 0.05,
    "p95_relative_reference_difference_max": 0.10,
    "reject_strict_monotonic_reference_trend": False,
    "numeric_comparison_relative_roundoff_tolerance": 1e-12,
    "all_endpoints_implementations_and_both_starts_required": True,
}


def validate_directory(path: Path) -> Path:
    candidate, root = path.absolute(), CACHE_ROOT.absolute()
    require(
        candidate != root and candidate.is_relative_to(root), "output must be below screen cache"
    )
    require(candidate.resolve().is_relative_to(root.resolve()), "output escapes screen cache")
    require(".." not in candidate.parts, "parent traversal in screen path")
    for component in (candidate, *candidate.parents):
        require(not component.is_symlink(), "symlink in screen output path")
    require(not candidate.exists(), "screen attempt already exists; never overwrite or resume")
    return candidate


def analyze_windows(windows: list[dict]) -> dict:
    require(len(windows) == 8, "exactly eight successive windows required")
    values = {
        field: [number(window[field], field, positive=True) for window in windows]
        for field in ("requests_per_second", "p95_response_time_ms")
    }
    limits = {"requests_per_second": 0.05, "p95_response_time_ms": 0.10}

    def spread(series):
        return (max(series) - min(series)) / median(series)

    def within_limit(value, limit):
        # Inclusive decimal bounds must not fail on machine-roundoff (e.g. 2.2/2).
        # The relative allowance is 1e-12 of the limit, not an extra tolerance band.
        return value <= limit or math.isclose(value, limit, rel_tol=1e-12, abs_tol=0.0)

    references = {field: median(series[5:]) for field, series in values.items()}
    reference_spreads = {field: spread(series[5:]) for field, series in values.items()}
    reference_stable = all(
        within_limit(reference_spreads[field], limits[field]) for field in values
    )
    monotonic = any(s[5] < s[6] < s[7] or s[5] > s[6] > s[7] for s in values.values())
    candidates = []
    for offset, seconds in enumerate(CANDIDATES):
        differences = {
            field: [abs(value - references[field]) / references[field] for value in series[offset:]]
            for field, series in values.items()
        }
        spreads = {field: spread(series[offset : offset + 3]) for field, series in values.items()}
        supported = reference_stable and all(
            within_limit(spreads[field], limits[field])
            and within_limit(max(differences[field]), limits[field])
            for field in values
        )
        candidates.append(
            {
                "cumulative_load_seconds": seconds,
                "first_measurement_window_indices": list(range(offset + 1, offset + 4)),
                "subsequent_window_indices": list(range(offset + 1, 9)),
                "first_three_range_over_median": spreads,
                "subsequent_relative_reference_differences": differences,
                "screen_supported": supported,
            }
        )
    return {
        "reference_window_indices": [6, 7, 8],
        "reference_medians": references,
        "reference_range_over_median": reference_spreads,
        "reference_stable": reference_stable,
        "strict_monotonic_reference_trend": monotonic,
        "candidates": candidates,
        "screened_candidate_seconds": [
            c["cumulative_load_seconds"] for c in candidates if c["screen_supported"]
        ],
    }


def run_study(directory: Path, factory, *, metadata: dict, contract=run_contract) -> dict:
    directory = validate_directory(directory)
    for key in ("source_commit", "source_tree"):
        require(
            type(metadata.get(key)) is str and re.fullmatch(r"[0-9a-f]{40}", metadata[key]),
            "missing source identity: " + key,
        )
    directory.mkdir(parents=True)
    conditions = copy.deepcopy(PROFILE)
    conditions.update(runs=8, clean_starts_per_endpoint=2, endpoint_reset=True)
    result = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "mode": "common-warmup-screen",
        "official": False,
        "publishable": False,
        "status": "running",
        "started_at": now(),
        "conditions": conditions,
        "criteria": copy.deepcopy(RULES),
        "metadata": copy.deepcopy(metadata),
        "validations": [
            {"implementation": identifier, "status": "not-started"} for identifier in MEMBERS
        ],
        "attempts": [
            {
                "round": round_number,
                "implementation": identifier,
                "endpoint": endpoint,
                "status": "not-started",
                "windows": [],
            }
            for round_number, order in enumerate(ORDERS, 1)
            for identifier, endpoint in order
        ],
    }
    output = directory / "screen.json"

    def persist():
        atomic_json(output, result)

    api_ids, database_ids, validated_images = set(), set(), {}

    def execute_entry(entry, label, *, validation):
        identifier = entry["implementation"]
        entry.update(status="running", started_at=now())
        persist()
        environment = None
        failure = None
        try:
            environment = factory(directory / label)
            require(environment.health_policy == EXTERNAL_READINESS, "external readiness required")
            require(
                environment.connections == 50 and environment.request_timeout == 15,
                "fixed load configuration required",
            )
            entry["artifact_directory"] = str(environment.artifacts.relative_to(directory))
            persist()
            environment.build(identifier)
            entry["container"] = environment.start(identifier)
            entry["readiness"] = copy.deepcopy(environment.readiness)
            persist()
            environment.check()
            container = entry["container"]
            api_id, database_id = container["id"], container["postgres"]["id"]
            require(
                api_id not in api_ids and database_id not in database_ids,
                "fresh API and database identities required",
            )
            api_ids.add(api_id)
            database_ids.add(database_id)
            if not validation:
                require(
                    container["image_id"] == validated_images[identifier],
                    "image differs from sacrificial contract validation",
                )
            if validation:
                with (
                    (environment.artifacts / "contract.log").open("w") as log,
                    contextlib.redirect_stdout(log),
                ):
                    checks = contract("http://127.0.0.1:8080", implementation=identifier)
                require(
                    type(checks) is int and checks == 2 * len(load_cases()),
                    "shared contract incomplete",
                )
                entry["contract_checks"] = checks
                validated_images[identifier] = container["image_id"]
            else:
                entry["warmup"] = environment.measure(entry["endpoint"], 5, 0)
                persist()
                for index in range(1, 9):
                    entry["windows"].append(environment.measure(entry["endpoint"], 30, index))
                    persist()
                entry["analysis"] = analyze_windows(entry["windows"])
            environment.check()
            persist()
        except BaseException as error:
            failure = error
            entry.update(status="failed", error=f"{type(error).__name__}: {error}")
            persist()
            raise
        finally:
            try:
                if environment is not None:
                    with protect_cleanup():
                        environment.cleanup()
                    entry["cleanup"] = "passed"
            except BaseException as cleanup_error:
                entry.update(status="failed", cleanup="failed", cleanup_error=str(cleanup_error))
                if failure is None:
                    raise
            finally:
                entry["completed_at"] = now()
                persist()
        entry["status"] = "completed"
        persist()

    persist()
    try:
        for index, entry in enumerate(result["validations"], 1):
            execute_entry(
                entry, f"validation-{index:02d}-{entry['implementation']}", validation=True
            )
        for index, entry in enumerate(result["attempts"], 1):
            execute_entry(entry, f"trace-{index:02d}-{entry['implementation']}", validation=False)
        candidates = [
            seconds
            for seconds in CANDIDATES
            if all(
                seconds in a["analysis"]["screened_candidate_seconds"] for a in result["attempts"]
            )
        ]
        result["assessment"] = {
            "screened_candidate_seconds": candidates,
            "outcome": "candidate-for-independent-confirmation" if candidates else "inconclusive",
            "official_admission": False,
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
    from .common_warmup_environment import CommonWarmupEnvironment
    from .environment import provenance, registered_pinned_versions
    from .install_oha import ensure_oha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker compose")
    args = parser.parse_args(argv)
    run_directory = CACHE_ROOT / ("study-" + uuid.uuid4().hex)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    bootstrap = CACHE_ROOT / (run_directory.name + "-bootstrap.json")
    context = {
        "protocol_id": PROTOCOL_ID,
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
            jit_gc_evidence="Unavailable: unchanged production runtimes; no JIT/GC instrumentation.",
        )
        run_study(
            run_directory,
            lambda root: CommonWarmupEnvironment(oha, root, compose=args.compose),
            metadata=metadata,
        )
        context["status"] = "completed"
        print(f"Common warm-up screen completed: {run_directory}; no official results published.")
        return 0
    except (Exception, KeyboardInterrupt) as error:
        context.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(f"Common warm-up screen failed without retry: {error}", file=sys.stderr)
        return 1
    finally:
        context["completed_at"] = now()
        atomic_json(bootstrap, context)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
