"""Non-publishing JVM diagnostic evidence without changing official measurements.

The inherited project lifecycle and resource checks remain unchanged. The only
load-window observer is the same sequential Docker stats command used by the
common environment, retaining its CPU field as well as its memory field.
"""

import contextlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .environment import DockerEnvironment, memory_bytes
from .healthcheck import EXTERNAL_READINESS
from .process import execute
from .results import parse_oha, require, strict_json


class DiagnosticEnvironment(DockerEnvironment):
    """Retain raw window evidence and scoped logs, including failed attempts."""

    def __init__(self, oha: Path, artifacts: Path, **kwargs):
        kwargs.setdefault("health_policy", EXTERNAL_READINESS)
        require(kwargs.get("connections", 50) == 50, "diagnostic connections must remain 50")
        require(
            kwargs.get("request_timeout", 15) == 15, "diagnostic request timeout must remain 15"
        )
        require(
            kwargs["health_policy"] == EXTERNAL_READINESS, "diagnostic requires external readiness"
        )
        require(kwargs.get("audit_health_events", False) is False, "diagnostic adds no event audit")
        super().__init__(oha, artifacts, **kwargs)

    def _failure(self, stage: str, error: BaseException) -> None:
        """Best-effort evidence must not replace the original failure.

        execute exposes the final 4,000 output characters for a nonzero exit;
        timeout/interruption output is not available from the shared helper.
        """
        try:
            (self.artifacts / f"{self.implementation}-{stage}-failure.log").write_text(
                f"{type(error).__name__}: {error}\n", encoding="utf-8"
            )
            try:
                output = execute(
                    self.prefix
                    + [
                        "logs",
                        "--no-color",
                        "--timestamps",
                        "--tail",
                        "200",
                        self.implementation,
                        "postgres",
                    ],
                    timeout=15,
                )
            except Exception as log_error:
                output = f"Container logs unavailable: {type(log_error).__name__}: {log_error}\n"
            (self.artifacts / f"{self.implementation}-{stage}-container.log").write_text(
                output, encoding="utf-8"
            )
        except Exception:
            # A full/unwritable disk must not mask the failure that stopped load.
            pass

    def build(self, implementation: str) -> None:
        self.implementation = implementation
        try:
            super().build(implementation)
        except BaseException as error:
            with contextlib.suppress(OSError):
                (self.artifacts / f"{implementation}-build.log").write_text(
                    f"{type(error).__name__}: {error}\n", encoding="utf-8"
                )
            self._failure("build", error)
            raise

    def start(self, implementation: str) -> dict:
        self.implementation = implementation
        try:
            context = super().start(implementation)
            state = self.inspect()
            # Never persist full inspect or Config.Env, which includes credentials.
            context.update(
                limits={
                    "nano_cpus": state["HostConfig"]["NanoCpus"],
                    "memory_bytes": state["HostConfig"]["Memory"],
                },
                container_started_at=state["State"]["StartedAt"],
                restart_count=state["RestartCount"],
                health_policy=self.health_policy,
                connections=self.connections,
                request_timeout_seconds=self.request_timeout,
            )
            (self.artifacts / f"{implementation}-context.json").write_text(
                json.dumps(context, indent=2) + "\n", encoding="utf-8"
            )
            return context
        except BaseException as error:
            self._failure("start", error)
            raise

    def measure(self, endpoint: str, duration: int, index: int) -> dict:
        """Use the common oha contract for each diagnostic window, including 0/4."""
        require(type(index) is int and 0 <= index <= 4, "window index must be 0 through 4")
        require(type(duration) is int and duration > 0, "window duration must be positive")
        require(
            endpoint in ("/json", "/db/42", "/cpu"),
            "diagnostic endpoint must be /json, /db/42 or /cpu",
        )
        label = endpoint.strip("/").replace("/", "-") + f"-window-{index}"
        path = self.artifacts / f"{self.implementation}-{label}.json"
        samples = []
        cpu_samples = []
        started = datetime.now(timezone.utc)
        clock_started = time.monotonic()
        completed = None
        elapsed = None
        status = "failed"
        failure = None
        result = None
        try:
            self.check()
            with (
                path.with_suffix(".stats.jsonl").open("w", encoding="utf-8") as stats_log,
                path.with_suffix(".memory.jsonl").open("w", encoding="utf-8") as memory_log,
            ):

                def sample():
                    self.check()
                    sample_started = datetime.now(timezone.utc)
                    raw = execute(
                        [
                            "docker",
                            "stats",
                            "--no-stream",
                            "--no-trunc",
                            "--format",
                            "{{json .}}",
                            self.container,
                        ],
                        timeout=8,
                    )
                    sample_completed = datetime.now(timezone.utc)
                    # Write before parsing so malformed samples survive a failure.
                    stats_log.write(
                        json.dumps(
                            {
                                "started_at": sample_started.isoformat(),
                                "completed_at": sample_completed.isoformat(),
                                "raw": raw,
                            }
                        )
                        + "\n"
                    )
                    stats_log.flush()
                    memory = memory_bytes(raw, self.container)
                    cpu_text = strict_json(raw.encode()).get("CPUPerc")
                    require(
                        type(cpu_text) is str
                        and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", cpu_text) is not None,
                        "Docker CPU sample has missing/invalid CPUPerc",
                    )
                    cpu = float(cpu_text[:-1])
                    require(math.isfinite(cpu), "Docker CPU sample is not finite")
                    samples.append(memory)
                    cpu_samples.append(cpu)
                    memory_log.write(
                        json.dumps(
                            {
                                "at": sample_completed.isoformat(),
                                "bytes": memory,
                                "cpu_percent": cpu,
                                "container_id": self.container,
                            }
                        )
                        + "\n"
                    )
                    memory_log.flush()

                started = datetime.now(timezone.utc)
                clock_started = time.monotonic()
                try:
                    output = execute(
                        [
                            str(self.oha),
                            "--no-tui",
                            "--output-format",
                            "json",
                            "--output",
                            str(path),
                            "--http-version",
                            "1.1",
                            "--redirect",
                            "0",
                            "--disable-compression",
                            "-c",
                            str(self.connections),
                            "-z",
                            f"{duration}s",
                            "-w",
                            "-t",
                            f"{self.request_timeout}s",
                            "--connect-timeout",
                            "5s",
                            "http://127.0.0.1:8080" + endpoint,
                        ],
                        timeout=duration + self.request_timeout + 15,
                        tick=sample,
                    )
                except BaseException as error:
                    with contextlib.suppress(OSError):
                        path.with_suffix(".load.log").write_text(
                            f"{type(error).__name__}: {error}\n", encoding="utf-8"
                        )
                    raise
                finally:
                    completed = datetime.now(timezone.utc)
                    elapsed = time.monotonic() - clock_started
                path.with_suffix(".load.log").write_text(output, encoding="utf-8")
            self.check()
            require(bool(samples), "memory/CPU collection produced no samples")
            require(
                path.is_file() and path.stat().st_size <= 1024 * 1024,
                "oha result missing or oversized",
            )
            raw = path.read_bytes()
            result = parse_oha(raw, duration=duration, request_timeout=self.request_timeout)
            result.update(
                run=max(index, 1),
                window_index=index,
                p95_response_time_ms=strict_json(raw)["latencyPercentiles"]["p95"] * 1000,
                peak_memory_bytes=max(samples),
                memory_samples=len(samples),
                cpu_percent_samples=cpu_samples,
                started_at=started.isoformat(),
                completed_at=completed.isoformat(),
                duration_wall_seconds=elapsed,
            )
            status = "complete"
            return result
        except BaseException as error:
            failure = f"{type(error).__name__}: {error}"
            self._failure(label, error)
            raise
        finally:
            if completed is None:
                completed = datetime.now(timezone.utc)
                elapsed = time.monotonic() - clock_started
            window = {
                "implementation": self.implementation,
                "endpoint": endpoint,
                "window_index": index,
                "requested_duration_seconds": duration,
                "started_at": started.isoformat(),
                "completed_at": completed.isoformat(),
                "duration_wall_seconds": elapsed,
                "status": status,
                "error": failure,
                "memory_samples": len(samples),
                "cpu_percent_samples": cpu_samples,
            }
            try:
                path.with_suffix(".window.json").write_text(
                    json.dumps(window, indent=2) + "\n", encoding="utf-8"
                )
            except OSError:
                if failure is None:
                    raise
