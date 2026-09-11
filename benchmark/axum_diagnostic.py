"""Exercise only Axum with a short, explicitly non-publishing load diagnostic."""

import argparse
import copy
import re
import signal
import sys
from pathlib import Path

from .contract_runner import protect_cleanup
from .contract_test import ContractFailure, load_cases, run_contract
from .definition import PROFILE
from .healthcheck import EXTERNAL_READINESS
from .registry import implementation
from .results import BenchmarkFailure, atomic_json, require, select_run, validate_run
from .run import now

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache" / "axum-diagnostic"
IMPLEMENTATION = "rust-axum"


def validate_output_path(path: Path) -> Path:
    """Never allow diagnostics to target results or traverse a symlink."""
    candidate = path.absolute()
    root = CACHE_ROOT.absolute()
    require(candidate.is_relative_to(root), "output must stay below Axum diagnostic cache")
    require(candidate.resolve().is_relative_to(root.resolve()), "output escapes diagnostic cache")
    require(candidate.name == "diagnostic.json", "expected diagnostic.json output")
    for component in (candidate, *candidate.parents):
        require(not component.is_symlink(), "symlink in diagnostic output path")
    return candidate


def run_diagnostic(environment, output: Path, *, metadata: dict, contract=run_contract) -> dict:
    """Run the unchanged shared contract and write only after all load and cleanup pass."""
    output = validate_output_path(output)
    spec = implementation(IMPLEMENTATION)
    for key in ("source_commit", "source_tree"):
        require(
            type(metadata.get(key)) is str and re.fullmatch(r"[0-9a-f]{40}", metadata[key]),
            "diagnostic source metadata missing " + key,
        )
    versions = metadata.get("versions", {})
    require(
        set(versions) == {IMPLEMENTATION}
        and set(spec["version_fields"]) <= set(versions[IMPLEMENTATION]),
        "diagnostic requires Axum version metadata",
    )
    require(environment.health_policy == EXTERNAL_READINESS, "diagnostic health policy differs")
    require(environment.connections == 2, "diagnostic connections must be 2")
    require(environment.request_timeout == 15, "diagnostic request timeout must be 15s")
    cases = load_cases()
    conditions = copy.deepcopy(PROFILE)
    conditions.update(warmup_seconds=1, duration_seconds=2, connections=2)
    started_at = now()
    failure = None
    try:
        environment.build(IMPLEMENTATION)
        container = environment.start(IMPLEMENTATION)
        checks = contract("http://127.0.0.1:8080", implementation=IMPLEMENTATION)
        require(
            type(checks) is int and checks == 2 * len(cases),
            "shared contract did not complete both rounds",
        )
        environment.check()
        endpoints = []
        for endpoint in conditions["endpoints"]:
            validate_run(environment.measure(endpoint, conditions["warmup_seconds"], 0))
            runs = []
            for index in (1, 2, 3):
                observed = environment.measure(endpoint, conditions["duration_seconds"], index)
                validate_run(observed)
                runs.append(observed)
            endpoints.append({"endpoint": endpoint, "runs": runs, "selected": select_run(runs)})
        environment.check()
        readiness = copy.deepcopy(environment.readiness)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            with protect_cleanup():
                environment.cleanup()
        except (BenchmarkFailure, OSError) as error:
            if failure is not None:
                raise BenchmarkFailure(f"{failure}; cleanup also failed: {error}") from failure
            raise
    result = {
        "schema_version": 1,
        "mode": "axum-diagnostic",
        "status": "verified",
        "official": False,
        "publishable": False,
        "implementation": IMPLEMENTATION,
        "started_at": started_at,
        "completed_at": now(),
        "conditions": conditions,
        "api_health_policy": EXTERNAL_READINESS,
        "runtime": {"executor": "tokio-current-thread", "async_workers": 1, "cpu_offload": False},
        "metadata": copy.deepcopy(metadata),
        "container": container,
        "readiness": readiness,
        "contract_checks": checks,
        "endpoints": endpoints,
    }
    atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    from .environment import DockerEnvironment, provenance, registered_pinned_versions
    from .install_oha import ensure_oha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker compose")
    args = parser.parse_args(argv)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        validate_output_path(CACHE_ROOT / "diagnostic.json")
        oha = ensure_oha()
        metadata = provenance(oha)
        metadata["versions"] = {IMPLEMENTATION: registered_pinned_versions()[IMPLEMENTATION]}
        environment = DockerEnvironment(
            oha,
            CACHE_ROOT,
            compose=args.compose,
            connections=2,
            request_timeout=15,
            health_policy=EXTERNAL_READINESS,
        )
        metadata["artifact_directory"] = str(environment.artifacts.relative_to(ROOT))
        output = environment.artifacts / "diagnostic.json"
        run_diagnostic(environment, output, metadata=metadata)
        print(f"Axum diagnostic passed: {output.relative_to(ROOT)}; no results published.")
        return 0
    except (BenchmarkFailure, ContractFailure, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Axum diagnostic failed: {error}", file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
