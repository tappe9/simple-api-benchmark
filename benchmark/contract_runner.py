"""Run the shared contract against sequential, isolated Compose services (POSIX)."""

import argparse
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from .contract_test import ContractFailure, load_cases, run_contract

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATIONS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


def command(arguments: list[str], *, timeout: float) -> None:
    """Bound each Compose operation and reap its process group before teardown."""
    print(f"+ {shlex.join(arguments)}", flush=True)
    try:
        process = subprocess.Popen(
            arguments,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as error:
        raise ContractFailure(f"cannot execute {arguments[0]}: {error}") from error
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException as error:
        # Killing only the CLI parent can leave the Compose plugin starting services.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            raise ContractFailure(
                f"command timeout after {timeout}s: {shlex.join(arguments)}"
            ) from error
        raise
    if process.returncode:
        raise ContractFailure(
            f"command exited {process.returncode}: {shlex.join(arguments)}\n{output[-4000:]}"
        )
    if output:
        print(output, end="", flush=True)


@contextlib.contextmanager
def protect_cleanup():
    """Do not abandon teardown on a second Ctrl-C or SIGTERM."""
    previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run_implementations(
    implementations: Sequence[str] = IMPLEMENTATIONS, *, compose: str = "docker compose"
) -> int:
    if not implementations or any(name not in IMPLEMENTATIONS for name in implementations):
        raise ContractFailure("select at least one of: " + ", ".join(IMPLEMENTATIONS))
    try:
        executable = shlex.split(compose)
    except ValueError as error:
        raise ContractFailure(f"invalid Compose command: {error}") from error
    if not executable:
        raise ContractFailure("Compose command must not be empty")
    load_cases()  # Reject an incomplete contract document before creating resources.
    project = "sab-contract-" + uuid.uuid4().hex[:12]
    prefix = executable + ["-f", str(ROOT / "docker-compose.yml"), "-p", project]
    checks = 0
    for implementation in implementations:
        print(f"[{implementation}] isolated Compose project: {project}", flush=True)
        failure = None
        try:
            command(prefix + ["build", implementation], timeout=900)
            command(
                prefix + ["up", "--detach", "--wait", "--wait-timeout", "60", implementation],
                timeout=120,
            )
            checks += run_contract("http://127.0.0.1:8080", implementation=implementation)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                with protect_cleanup():
                    command(
                        prefix + ["down", "--remove-orphans", "--volumes", "--timeout", "10"],
                        timeout=60,
                    )
            except ContractFailure as cleanup_error:
                if failure is None:
                    raise
                print(
                    f"[{implementation}] cleanup also failed for {project}: {cleanup_error}",
                    file=sys.stderr,
                )
        print(f"[{implementation}] cleanup complete", flush=True)
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", choices=("all", *IMPLEMENTATIONS), default="all")
    parser.add_argument("--compose", default="docker compose")
    args = parser.parse_args(argv)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        selected = IMPLEMENTATIONS if args.implementation == "all" else (args.implementation,)
        checks = run_implementations(selected, compose=args.compose)
    except (ContractFailure, KeyboardInterrupt) as error:
        print(f"Contract failed: {error}", file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(f"{checks} contract checks passed; all test environments removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
