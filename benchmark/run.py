"""Run all four APIs sequentially; publish only after every run and cleanup passes."""

import argparse
import copy
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from .contract_runner import IMPLEMENTATIONS, protect_cleanup
from .contract_test import ContractFailure, load_cases, run_contract
from .results import (
    BenchmarkFailure,
    atomic_json,
    object_fields,
    require,
    select_run,
    strict_json,
    validate_run,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {
    "schema_version": 1,
    "api_cpus": 1,
    "api_memory_bytes": 536870912,
    "workers": 1,
    "pool_max": 10,
    "http_version": "1.1",
    "warmup_seconds": 5,
    "duration_seconds": 30,
    "connections": 50,
    "runs": 3,
    "request_timeout_seconds": 15,
    "endpoints": ["/json", "/db/42", "/cpu"],
}


def load_config(path: Path = ROOT / "benchmark" / "config.json") -> dict:
    config = object_fields(strict_json(path.read_bytes()), PROFILE, "config")
    for field, expected in PROFILE.items():
        require(
            type(config[field]) is type(expected) and config[field] == expected,
            f"config.{field}: v0.1 requires {expected!r}; baseline changes need explicit review",
        )
    return config


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_benchmark(
    environment, config: dict, output: Path, *, metadata: dict, contract=None, smoke: bool = False
) -> dict:
    load_cases()  # Fail closed on a malformed shared contract before starting resources.
    contract = run_contract if contract is None else contract
    conditions = copy.deepcopy(config)
    if smoke:
        conditions.update(warmup_seconds=1, duration_seconds=2, connections=2)
    report = {
        "schema_version": 1,
        "status": "verified",
        "mode": "smoke" if smoke else "local",
        "official": False,
        "started_at": now(),
        "conditions": conditions,
        "metadata": metadata,
        "implementations": [],
    }
    for implementation in IMPLEMENTATIONS:
        failure = None
        stage = "build"
        print(
            f"[{implementation}] build -> readiness -> contract -> warmup -> three measured runs",
            flush=True,
        )
        try:
            environment.build(implementation)
            stage = "startup/readiness"
            information = environment.start(implementation)
            stage = "shared contract"
            checks = contract("http://127.0.0.1:8080", implementation=implementation)
            require(
                type(checks) is int and checks == 2 * len(load_cases()),
                "shared contract did not complete both rounds",
            )
            environment.check()
            backend = {
                "implementation": implementation,
                "container": information,
                "contract_checks": checks,
                "endpoints": [],
            }
            for endpoint in conditions["endpoints"]:
                stage = endpoint + " warmup"
                environment.measure(endpoint, conditions["warmup_seconds"], 0)
                runs = []
                for index in (1, 2, 3):
                    stage = f"{endpoint} measured run {index}/3"
                    summary = environment.measure(endpoint, conditions["duration_seconds"], index)
                    validate_run(summary)
                    runs.append(summary)
                backend["endpoints"].append(
                    {"endpoint": endpoint, "runs": runs, "selected": select_run(runs)}
                )
            environment.check()
            report["implementations"].append(backend)
        except (BenchmarkFailure, ContractFailure, OSError, ValueError) as error:
            failure = error
            raise BenchmarkFailure(f"[{implementation}] {stage}: {error}") from error
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                with protect_cleanup():
                    environment.cleanup()
            except (BenchmarkFailure, OSError) as error:
                if failure is None:
                    raise BenchmarkFailure(f"[{implementation}] cleanup: {error}") from error
                print(f"[{implementation}] cleanup also failed: {error}", file=sys.stderr)
    report["completed_at"] = now()
    if not smoke:
        atomic_json(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    from .environment import DockerEnvironment, provenance
    from .install_oha import ensure_oha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker compose")
    parser.add_argument(
        "--smoke", action="store_true", help="short diagnostic only; never writes latest.json"
    )
    parser.add_argument(
        "--install-only", action="store_true", help="verify/install pinned oha without Docker"
    )
    args = parser.parse_args(argv)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        config = load_config()
        oha = ensure_oha()
        if args.install_only:
            print(oha)
            return 0
        metadata = provenance(oha)
        environment = DockerEnvironment(
            oha,
            ROOT / ".cache" / "benchmark",
            compose=args.compose,
            connections=2 if args.smoke else config["connections"],
            request_timeout=config["request_timeout_seconds"],
        )
        metadata["artifact_directory"] = str(environment.artifacts.relative_to(ROOT))
        report = run_benchmark(
            environment,
            config,
            ROOT / "results" / "latest.json",
            metadata=metadata,
            smoke=args.smoke,
        )
        # The smoke diagnostic belongs only in its isolated artifact directory.
        if args.smoke:
            atomic_json(environment.artifacts / "smoke.json", report)
        print(
            "Smoke passed; latest.json unchanged."
            if args.smoke
            else "Complete local benchmark saved to results/latest.json (not an official published result)."
        )
        return 0
    except (BenchmarkFailure, ContractFailure, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
