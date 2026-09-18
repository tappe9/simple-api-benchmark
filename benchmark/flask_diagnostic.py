"""Counterbalanced Flask hypothesis probes; never an official performance result."""

import argparse
import copy
import hashlib
import json
import re
import signal
import sys
import uuid
from pathlib import Path

from .contract_runner import protect_cleanup
from .contract_test import ContractFailure, load_cases, run_contract
from .environment import DockerEnvironment
from .healthcheck import EXTERNAL_READINESS
from .process import ROOT, execute
from .registry import implementation
from .results import BenchmarkFailure, atomic_json, require, select_run, strict_json, validate_run
from .run import now

CACHE_ROOT = ROOT / ".cache" / "flask-diagnostic"
IMPLEMENTATION = "python-flask"
INITIAL_ARMS = ("baseline", "switch-1ms", "queue-quiet")
ARMS = (*INITIAL_ARMS, "affinity-one")


def diagnostic_plan(phase: str = "initial") -> list[dict]:
    """Fix order before collecting data; reverse arms and endpoints in block two."""
    require(phase in ("initial", "scheduling"), "unknown diagnostic phase")
    if phase == "scheduling":
        return [
            {
                "id": f"block-{index}-{arm}",
                "block": index,
                "arm": arm,
                "endpoints": ["/json", "/db/42"],
            }
            for index, arm in enumerate(("baseline", "affinity-one", "baseline"), 1)
        ]
    return [
        {
            "id": f"block-{block}-{arm}",
            "block": block,
            "arm": arm,
            "endpoints": ["/json", "/db/42"] if block == 1 else ["/db/42", "/json"],
        }
        for block, arms in ((1, INITIAL_ARMS), (2, tuple(reversed(INITIAL_ARMS))))
        for arm in arms
    ]


def validate_output_path(path: Path) -> Path:
    candidate = path.absolute()
    root = CACHE_ROOT.absolute()
    require(candidate.is_relative_to(root), "output must stay below Flask diagnostic cache")
    require(candidate.resolve().is_relative_to(root.resolve()), "output escapes diagnostic cache")
    require(candidate.name == "diagnostic.json", "expected diagnostic.json output")
    for component in (candidate, *candidate.parents):
        require(not component.is_symlink(), "symlink in diagnostic output path")
    return candidate


def hook_source(arm: str) -> str:
    """Only fixed, reviewed interventions are allowed; baseline has no startup hook."""
    require(arm in ARMS, "unknown diagnostic arm")
    if arm == "baseline":
        return ""
    intervention = {
        "switch-1ms": "sys.setswitchinterval(0.001)",
        "queue-quiet": 'logging.getLogger("waitress.queue").disabled = True',
        "affinity-one": "os.sched_setaffinity(0, {allowed_before[0]})",
    }[arm]
    return (
        "import json, logging, os, sys\n"
        "allowed_before = sorted(os.sched_getaffinity(0))\n"
        + intervention
        + "\nif os.getpid() == 1:\n"
        + '    print("FLASK_DIAGNOSTIC " + json.dumps({"arm": '
        + repr(arm)
        + ', "pid": os.getpid(), "interval": sys.getswitchinterval(), '
        + '"queue_disabled": logging.getLogger("waitress.queue").disabled, '
        + '"allowed_before": allowed_before, "allowed_after": sorted(os.sched_getaffinity(0)), '
        + '"gil_enabled": getattr(sys, "_is_gil_enabled", lambda: None)()}), flush=True)\n'
    )


def compose_override(arm: str, hook: Path) -> dict:
    hook_source(arm)  # Validate before producing any container configuration.
    if arm == "baseline":
        return {}
    return {
        "services": {
            IMPLEMENTATION: {
                "environment": {"PYTHONPATH": "/flask-diagnostic"},
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(hook.resolve()),
                        "target": "/flask-diagnostic",
                        "read_only": True,
                    }
                ],
            }
        }
    }


class FlaskEnvironment(DockerEnvironment):
    """Keep production image/entrypoint intact and instrument only between windows."""

    def __init__(self, oha: Path, directory: Path, arm: str):
        super().__init__(oha, directory, health_policy=EXTERNAL_READINESS)
        self.arm = arm
        self.since = now()
        self.hook_evidence = None
        if arm != "baseline":
            hook = self.artifacts / "hook"
            hook.mkdir()
            content = hook_source(arm)
            (hook / "sitecustomize.py").write_text(content, encoding="utf-8")
            override = self.artifacts / "diagnostic.compose.json"
            atomic_json(override, compose_override(arm, hook))
            self.prefix = self.prefix[:-2] + ["-f", str(override), *self.prefix[-2:]]
            self.hook_evidence = {"sha256": hashlib.sha256(content.encode()).hexdigest()}

    def start(self, identifier: str) -> dict:
        result = super().start(identifier)
        if self.arm != "baseline":
            logs = execute(["docker", "logs", "--tail", "100", self.container], timeout=10)
            markers = [
                line.removeprefix("FLASK_DIAGNOSTIC ")
                for line in logs.splitlines()
                if line.startswith("FLASK_DIAGNOSTIC ")
            ]
            require(len(markers) == 1, "diagnostic startup hook was not observed exactly once")
            observed = strict_json(markers[0].encode())
            require(
                observed.get("arm") == self.arm and observed.get("pid") == 1,
                "hook belongs to wrong process/arm",
            )
            require(
                observed.get("queue_disabled") is (self.arm == "queue-quiet"),
                "queue logger intervention mismatch",
            )
            require(
                observed.get("interval") == (0.001 if self.arm == "switch-1ms" else 0.005),
                "thread interval intervention mismatch",
            )
            before = observed.get("allowed_before")
            require(type(before) is list and bool(before), "missing allowed CPU set")
            expected = before[:1] if self.arm == "affinity-one" else before
            require(observed.get("allowed_after") == expected, "CPU affinity intervention mismatch")
            self.hook_evidence["observed"] = observed
        result["diagnostic_hook"] = self.hook_evidence
        return result

    def observe(self, label: str) -> dict:
        """Snapshots include collection overhead; no exec/polling runs during oha."""
        self.check()
        require(re.fullmatch(r"[a-z0-9-]+", label) is not None, "invalid observation label")
        script = """import json, os, sys
from pathlib import Path
paths = ['/sys/fs/cgroup/cpu.stat', '/proc/1/stat', '/proc/1/status']
result = {p: Path(p).read_text()[:16384] if Path(p).is_file() else None for p in paths}
threads = {}
vanished = []
for path in sorted(Path('/proc/1/task').glob('[0-9]*'))[:64]:
    try:
        threads[path.name] = {name: (path / name).read_text()[:16384]
                              for name in ('comm', 'stat', 'schedstat', 'status')}
    except FileNotFoundError:
        vanished.append(path.name)
result['threads'] = threads
result['vanished_threads'] = vanished
result['helper_runtime_not_pid1'] = {'version': sys.version,
    'gil_enabled': getattr(sys, '_is_gil_enabled', lambda: None)(),
    'affinity': sorted(os.sched_getaffinity(0))}
print(json.dumps(result))
"""
        raw = execute(["docker", "exec", self.container, "python", "-c", script], timeout=10)
        counters = strict_json(raw.encode())
        logs = execute(
            [
                "docker",
                "logs",
                "--timestamps",
                "--since",
                self.since,
                "--tail",
                "10000",
                self.container,
            ],
            timeout=10,
        )
        encoded = logs.encode()
        limited = encoded[-2 * 1024 * 1024 :]
        log_path = self.artifacts / f"{label}.server.log"
        log_path.write_bytes(limited)
        snapshot = {
            "at": now(),
            "container_id": self.container,
            "counters": counters,
            "server_log": log_path.name,
            "log_tail_limit_lines": 10000,
            "log_tail_may_be_truncated": len(logs.splitlines()) >= 10000
            or len(limited) != len(encoded),
            "queue_warning_lines_in_tail": limited.count(b"Task queue depth is"),
        }
        atomic_json(self.artifacts / f"{label}.observation.json", snapshot)
        self.check()
        return snapshot


def run_cell(environment, cell: dict, *, contract=run_contract, expected_image=None) -> dict:
    failure = None
    try:
        require(environment.health_policy == EXTERNAL_READINESS, "diagnostic health policy differs")
        require(environment.connections == 50, "diagnostic connections must be 50")
        require(environment.request_timeout == 15, "diagnostic request timeout must be 15s")
        environment.build(IMPLEMENTATION)
        container = environment.start(IMPLEMENTATION)
        if expected_image is not None:
            require(
                container.get("image_id") == expected_image,
                "diagnostic image changed between cells",
            )
        checks = contract("http://127.0.0.1:8080", implementation=IMPLEMENTATION)
        require(
            type(checks) is int and checks == 2 * len(load_cases()), "incomplete shared contract"
        )
        environment.check()
        endpoints = []
        for endpoint in cell["endpoints"]:
            label = endpoint.strip("/").replace("/", "-")
            before = environment.observe(label + "-before")
            warmup = environment.measure(endpoint, 5, 0)
            validate_run(warmup)
            runs = []
            for index in (1, 2, 3):
                observed = environment.measure(endpoint, 10, index)
                validate_run(observed)
                runs.append(observed)
            after = environment.observe(label + "-after")
            endpoints.append(
                {
                    "endpoint": endpoint,
                    "warmup": warmup,
                    "runs": runs,
                    "selected": select_run(runs),
                    "before": before,
                    "after": after,
                }
            )
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
    return {
        **cell,
        "container": container,
        "readiness": readiness,
        "contract_checks": checks,
        "artifact_directory": str(environment.artifacts),
        "endpoints": endpoints,
    }


def run_diagnostic(
    factory, output: Path, *, metadata: dict, contract=run_contract, phase="initial"
) -> dict:
    output = validate_output_path(output)
    for key in ("source_commit", "source_tree"):
        require(
            type(metadata.get(key)) is str and re.fullmatch(r"[0-9a-f]{40}", metadata[key]),
            "diagnostic source metadata missing " + key,
        )
    versions = metadata.get("versions", {})
    require(
        set(versions) == {IMPLEMENTATION}
        and set(implementation(IMPLEMENTATION)["version_fields"]) <= set(versions[IMPLEMENTATION]),
        "diagnostic requires Flask version metadata",
    )
    plan = diagnostic_plan(phase)
    started_at = now()
    cells = []
    progress = output.parent / "progress.json"
    for cell in plan:
        atomic_json(
            progress,
            {
                "status": "running",
                "official": False,
                "publishable": False,
                "metadata": metadata,
                "plan": plan,
                "active_cell": cell["id"],
                "cells": cells,
            },
        )
        print(f"Flask diagnostic {cell['id']}", flush=True)
        try:
            environment = factory(cell)
            expected_image = cells[0]["container"]["image_id"] if cells else None
            cells.append(
                run_cell(environment, cell, contract=contract, expected_image=expected_image)
            )
        except BaseException as error:
            atomic_json(
                progress,
                {
                    "status": "failed",
                    "official": False,
                    "publishable": False,
                    "metadata": metadata,
                    "plan": plan,
                    "failed_cell": cell["id"],
                    "error_type": type(error).__name__,
                    "cells": cells,
                },
            )
            raise
    result = {
        "schema_version": 1,
        "mode": "flask-diagnostic",
        "status": "verified",
        "official": False,
        "publishable": False,
        "implementation": IMPLEMENTATION,
        "started_at": started_at,
        "completed_at": now(),
        "metadata": copy.deepcopy(metadata),
        "phase": phase,
        "conditions": {
            "connections": 50,
            "warmup_seconds": 5,
            "duration_seconds": 10,
            "runs": 3,
            "api_health_policy": EXTERNAL_READINESS,
        },
        "limitations": [
            "Non-publishing diagnostic, not an official result or framework ranking.",
            "CPU snapshots span warm-up and measurement plus observation overhead.",
            "Server logs are bounded tails; warning counts may be lower bounds.",
            "A bounded diagnostic matrix does not establish cross-host or universal performance effects.",
        ],
        "plan": plan,
        "cells": cells,
    }
    atomic_json(output, result)
    atomic_json(
        progress,
        {
            "status": "completed",
            "official": False,
            "publishable": False,
            "metadata": metadata,
            "plan": plan,
            "cells": cells,
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    from .environment import provenance, registered_pinned_versions
    from .install_oha import ensure_oha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("initial", "scheduling"), default="initial")
    args = parser.parse_args(argv)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        directory = CACHE_ROOT / uuid.uuid4().hex
        output = validate_output_path(directory / "diagnostic.json")
        oha = ensure_oha()
        metadata = provenance(oha)
        metadata["versions"] = {IMPLEMENTATION: registered_pinned_versions()[IMPLEMENTATION]}
        metadata["diagnostic_plan_sha256"] = hashlib.sha256(
            json.dumps(diagnostic_plan(args.phase), sort_keys=True).encode()
        ).hexdigest()
        run_diagnostic(
            lambda cell: FlaskEnvironment(oha, directory / cell["id"], cell["arm"]),
            output,
            metadata=metadata,
            phase=args.phase,
        )
        print(f"Flask diagnostic complete: {output}; no results published.")
        return 0
    except (BenchmarkFailure, ContractFailure, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Flask diagnostic failed: {error}", file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
