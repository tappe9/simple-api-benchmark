"""Bound external commands and kill/reap the entire process group on failure."""

import contextlib
import os
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]


def execute(
    arguments: list[str], *, timeout: float, tick: Callable | None = None, cwd: Path = ROOT
) -> str:
    """A tick may collect metrics while the child runs; tick failures stop load.

    Files instead of pipes prevent a verbose build or load generator from filling
    an unread pipe. Each nested metric command has its own finite deadline.
    """
    with tempfile.TemporaryFile() as output:
        try:
            child = subprocess.Popen(
                arguments, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
            )
        except OSError as error:
            raise BenchmarkFailure(f"cannot execute {arguments[0]}: {error}") from error
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise BenchmarkFailure(
                        f"command timeout after {timeout}s: {shlex.join(arguments)}"
                    )
                if tick is not None:
                    tick()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BenchmarkFailure(
                        f"command timeout after {timeout}s: {shlex.join(arguments)}"
                    )
                try:
                    child.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            child.wait()
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise
        finally:
            # Even a parent that exits early must not leave background descendants.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
        if child.returncode:
            raise BenchmarkFailure(
                f"command exited {child.returncode}: {shlex.join(arguments)}\n{text[-4000:]}"
            )
        return text
