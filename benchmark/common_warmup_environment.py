"""Evidence-preserving environment for the separate common-warmup screen.

The original JVM environment keeps its 0..4 protocol. This module deliberately
owns its 0..8 window implementation rather than extending that existing protocol.
All load arguments and sequential CPU/memory sampling follow the common runner.
"""

import contextlib
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .contract_test import read_response
from .environment import ROOT, memory_bytes, validate_processes, validate_state
from .healthcheck import override_text, wait_external_readiness
from .jvm_environment import DiagnosticEnvironment
from .process import execute
from .results import BenchmarkFailure, parse_oha, require, strict_json


class CommonWarmupEnvironment(DiagnosticEnvironment):
    """One fresh API/PostgreSQL pair; no contract preheating or runtime tuning."""

    def __init__(self, oha: Path, artifacts: Path, **kwargs):
        super().__init__(oha, artifacts, **kwargs)
        self.postgres_container = None
        self.postgres_identity = None
        self.readiness_completed_at = None
        self.previous_window_completed_at = None
        self.start_attempted = False

    def _failure(self, stage: str, error: BaseException) -> None:
        # Shared execute retains only final 4,000 nonzero-exit output characters;
        # timeout/interruption output is unavailable. Never mask the first cause.
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
            pass

    def build(self, implementation: str) -> None:
        self.implementation = implementation
        try:
            output = execute(self.prefix + ["build", implementation], timeout=900)
            (self.artifacts / f"{implementation}-build.log").write_text(output, encoding="utf-8")
        except BaseException as error:
            with contextlib.suppress(OSError):
                (self.artifacts / f"{implementation}-build.log").write_text(
                    f"{type(error).__name__}: {error}\n", encoding="utf-8"
                )
            self._failure("build", error)
            raise

    def _append(self, suffix: str, record: dict) -> None:
        with (self.artifacts / f"{self.implementation}-{suffix}.jsonl").open(
            "a", encoding="utf-8"
        ) as output:
            output.write(json.dumps(record) + "\n")
            output.flush()

    @staticmethod
    def _safe_state(value: dict) -> dict:
        """Allowlist raw inspection fields; omit Env, health logs and other labels."""

        def selected(source, fields):
            if type(source) is not dict:
                return {"invalid_type": type(source).__name__}
            return {key: source[key] for key in fields if key in source}

        state = value.get("State", {})
        config = value.get("Config", {})
        host = value.get("HostConfig", {})
        result = selected(value, ("Id", "Image", "RestartCount"))
        result["State"] = selected(
            state,
            (
                "Status",
                "Running",
                "Restarting",
                "Dead",
                "OOMKilled",
                "StartedAt",
                "FinishedAt",
                "ExitCode",
            ),
        )
        if type(state) is dict and "Health" in state:
            result["State"]["Health"] = selected(state["Health"], ("Status",))
        result["HostConfig"] = selected(host, ("NanoCpus", "Memory"))
        if type(host) is dict:
            result["HostConfig"]["RestartPolicy"] = selected(
                host.get("RestartPolicy", {}), ("Name",)
            )
            if "Tmpfs" in host:
                result["HostConfig"]["Tmpfs"] = selected(host["Tmpfs"], ("/var/lib/postgresql",))
        if type(value.get("Mounts")) is list:
            result["Mounts"] = [
                selected(mount, ("Type", "Source", "Destination", "RW"))
                for mount in value["Mounts"]
                if type(mount) is dict
                and (
                    mount.get("Destination") == "/docker-entrypoint-initdb.d/001-init.sql"
                    or str(mount.get("Destination", "")).startswith("/var/lib/postgresql")
                )
            ]
        result["Config"] = {}
        if type(config) is dict:
            result["Config"]["Labels"] = selected(
                config.get("Labels", {}),
                ("com.docker.compose.project", "com.docker.compose.service"),
            )
            health = config.get("Healthcheck")
            result["Config"]["healthcheck_disabled"] = type(health) is dict and health.get(
                "Test"
            ) == ["NONE"]
        return result

    def _inspect_owned(self, container: str, role: str) -> dict:
        started = datetime.now(timezone.utc)
        record = {
            "role": role,
            "requested_container_id": container,
            "started_at": started.isoformat(),
        }
        try:
            raw = execute(["docker", "inspect", container], timeout=10)
            data = strict_json(raw.encode())
            require(
                type(data) is list and len(data) == 1 and type(data[0]) is dict,
                f"{role} container inspect missing",
            )
            record["raw"] = self._safe_state(data[0])
            return data[0]
        except BaseException as error:
            record["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
            try:
                self._append("state", record)
            except OSError:
                if "error" not in record:
                    raise

    def inspect(self) -> dict:
        state = self._inspect_owned(self.container, "api")
        require(state.get("Id") == self.container, "API container identity mismatch")
        return state

    def check(self) -> None:
        state = self.inspect()
        validate_state(state, self.project, self.implementation, self.identity)
        require(
            state.get("Config", {}).get("Healthcheck", {}).get("Test") == ["NONE"],
            "measured API healthcheck must be disabled",
        )

    def _check_postgres(self) -> dict:
        state = self._inspect_owned(self.postgres_container, "postgres")
        try:
            status = state["State"]
            labels = state["Config"]["Labels"]
            require(
                state["Id"] == self.postgres_container
                and re.fullmatch(r"[0-9a-f]{64}", state["Id"]) is not None,
                "PostgreSQL container identity mismatch",
            )
            require(
                labels["com.docker.compose.project"] == self.project
                and labels["com.docker.compose.service"] == "postgres",
                "PostgreSQL container belongs to wrong project/service",
            )
            require(
                status["Running"] is True
                and status["Restarting"] is False
                and status["Dead"] is False
                and status["OOMKilled"] is False
                and status["Status"] == "running"
                and status.get("Health", {}).get("Status") == "healthy",
                "PostgreSQL is not healthy/running or was OOM-killed",
            )
            require(
                type(state["RestartCount"]) is int and state["RestartCount"] == 0,
                "PostgreSQL restart detected",
            )
            require(
                state["HostConfig"]["RestartPolicy"]["Name"] == "no",
                "PostgreSQL restart policy must be no",
            )
            require(
                type(state["HostConfig"].get("Tmpfs")) is dict
                and bool(state["HostConfig"]["Tmpfs"].get("/var/lib/postgresql")),
                "PostgreSQL data must use fresh tmpfs",
            )
            mounts = state.get("Mounts", [])
            require(
                type(mounts) is list and all(type(mount) is dict for mount in mounts),
                "PostgreSQL mount evidence unavailable",
            )
            require(
                not any(
                    str(mount.get("Destination", "")).startswith("/var/lib/postgresql")
                    and mount.get("Type") != "tmpfs"
                    for mount in mounts
                ),
                "PostgreSQL must not use persistent data mounts",
            )
            fixture_mounts = [
                mount
                for mount in mounts
                if mount.get("Destination") == "/docker-entrypoint-initdb.d/001-init.sql"
            ]
            require(
                len(fixture_mounts) == 1
                and fixture_mounts[0].get("Type") == "bind"
                and fixture_mounts[0].get("RW") is False,
                "PostgreSQL fixture mount must be read-only",
            )
            self._parse_started_at(status["StartedAt"])
            identity = (state["Id"], status["StartedAt"])
            require(
                self.postgres_identity is None or identity == self.postgres_identity,
                "PostgreSQL container identity/start time changed",
            )
            self.postgres_identity = identity
            return state
        except (KeyError, TypeError) as error:
            raise BenchmarkFailure(f"incomplete PostgreSQL container state: {error}") from error

    @staticmethod
    def _parse_started_at(value: str) -> datetime:
        try:
            require(type(value) is str and value.endswith("Z"), "missing container start time")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            require(parsed.tzinfo is not None, "container start time must have timezone")
            return parsed
        except (ValueError, TypeError) as error:
            raise BenchmarkFailure("invalid container start time") from error

    def _readiness_request(self, base_url, path, *, timeout):
        record = {
            "path": path,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": timeout,
        }
        try:
            response = read_response(base_url, path, timeout=timeout)
            record["response"] = {
                "status": response.status,
                "content_type": response.content_type,
                "body": response.body.decode("utf-8", errors="replace"),
            }
            return response
        except BaseException as error:
            record["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
            try:
                self._append("readiness", record)
            except OSError:
                if "error" not in record:
                    raise

    def start(self, implementation: str) -> dict:
        require(not self.start_attempted, "start requires a fresh environment instance")
        self.start_attempted = True
        self.implementation = implementation
        try:
            override = self.artifacts / f"{implementation}-external-readiness.compose.yml"
            override.write_text(override_text(implementation), encoding="utf-8")
            runtime = self.prefix[:-2] + ["-f", str(override), *self.prefix[-2:]]
            output = execute(
                runtime + ["up", "--detach", "--wait", "--wait-timeout", "60", "postgres"],
                timeout=120,
            )
            (self.artifacts / f"{implementation}-postgres-start.log").write_text(
                output, encoding="utf-8"
            )
            self.postgres_container = execute(
                runtime + ["ps", "--quiet", "postgres"], timeout=10
            ).strip()
            require(
                re.fullmatch(r"[0-9a-f]{64}", self.postgres_container) is not None,
                "expected one full PostgreSQL container ID",
            )
            pg_state = self._check_postgres()
            psql = runtime + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-U",
                "benchmark",
                "-d",
                "benchmark",
                "--set",
                "ON_ERROR_STOP=1",
                "-At",
            ]
            pg_version = execute(psql + ["-c", "SELECT version();"], timeout=15).strip()
            require(pg_version.startswith("PostgreSQL "), "PostgreSQL version collection failed")
            fixture = execute(
                psql
                + [
                    "-F",
                    "|",
                    "-c",
                    "SELECT id, name, price FROM items WHERE id = 42; SELECT COUNT(*) FROM items;",
                ],
                timeout=15,
            )
            (self.artifacts / f"{implementation}-postgres-fixture.log").write_text(
                fixture, encoding="utf-8"
            )
            require(
                fixture.strip().splitlines() == ["42|Item 42|4200", "1"],
                "PostgreSQL benchmark fixture mismatch",
            )
            postgres = {
                "id": pg_state["Id"],
                "image_id": pg_state["Image"],
                "container_started_at": pg_state["State"]["StartedAt"],
                "restart_count": pg_state["RestartCount"],
                "version": pg_version,
                "fixture": {"id": 42, "name": "Item 42", "price": 4200, "row_count": 1},
                "tmpfs": self._safe_state(pg_state)["HostConfig"]["Tmpfs"],
                "mounts": self._safe_state(pg_state)["Mounts"],
                "fixture_source_sha256": hashlib.sha256(
                    (ROOT / "database/init.sql").read_bytes()
                ).hexdigest(),
            }
            output = execute(runtime + ["up", "--detach", implementation], timeout=120)
            (self.artifacts / f"{implementation}-api-start.log").write_text(
                output, encoding="utf-8"
            )
            self.container = execute(
                runtime + ["ps", "--quiet", implementation], timeout=10
            ).strip()
            require(
                re.fullmatch(r"[0-9a-f]{64}", self.container) is not None,
                "expected one full API container ID",
            )
            state = self.inspect()
            self.identity = validate_state(state, self.project, implementation)
            self._parse_started_at(self.identity[1])
            require(
                state.get("Config", {}).get("Healthcheck", {}).get("Test") == ["NONE"],
                "measured API healthcheck must be disabled",
            )
            readiness_started = datetime.now(timezone.utc)
            self.readiness = wait_external_readiness(
                "http://127.0.0.1:8080",
                implementation,
                self.check,
                timeout_seconds=60.0,
                request_timeout=2.0,
                reader=self._readiness_request,
            )
            self.readiness_completed_at = datetime.now(timezone.utc)
            self.readiness.update(
                started_at=readiness_started.isoformat(),
                completed_at=self.readiness_completed_at.isoformat(),
                path="/health",
            )
            # Preserve the common runner's ordering: workers may still be starting
            # until /health responds, even though the container is already running.
            process_list = execute(["docker", "top", self.container, "-eo", "pid,args"], timeout=10)
            (self.artifacts / f"{implementation}-processes.log").write_text(
                process_list, encoding="utf-8"
            )
            validate_processes(state, process_list, allow_health_probe=False)
            self._check_postgres()
            context = {
                "id": self.container,
                "image_id": state["Image"],
                "command": [state["Path"], *state["Args"]],
                "postgresql_version": pg_version,
                "postgres": postgres,
                "limits": {
                    "nano_cpus": state["HostConfig"]["NanoCpus"],
                    "memory_bytes": state["HostConfig"]["Memory"],
                },
                "container_started_at": state["State"]["StartedAt"],
                "restart_count": state["RestartCount"],
                "health_policy": self.health_policy,
                "connections": self.connections,
                "request_timeout_seconds": self.request_timeout,
                "readiness": self.readiness,
            }
            (self.artifacts / f"{implementation}-context.json").write_text(
                json.dumps(context, indent=2) + "\n", encoding="utf-8"
            )
            return context
        except BaseException as error:
            self._failure("start", error)
            raise

    def _timing(self, started: datetime, completed: datetime) -> dict:
        born = self._parse_started_at(self.identity[1])
        age = (started - born).total_seconds()
        require(age >= 0, "container start time is later than host window clock")
        return {
            "process_age_seconds_at_start": age,
            "process_age_seconds_at_completion": (completed - born).total_seconds(),
            "readiness_to_window_seconds": (started - self.readiness_completed_at).total_seconds(),
            "gap_since_previous_window_seconds": None
            if self.previous_window_completed_at is None
            else (started - self.previous_window_completed_at).total_seconds(),
        }

    def measure(self, endpoint: str, duration: int, index: int) -> dict:
        """Use the common oha contract for each diagnostic window, including 0/8."""
        require(type(index) is int and 0 <= index <= 8, "window index must be 0 through 8")
        require(type(duration) is int and duration > 0, "window duration must be positive")
        require(
            endpoint in ("/json", "/db/42", "/cpu"),
            "diagnostic endpoint must be /json, /db/42 or /cpu",
        )
        label = endpoint.strip("/").replace("/", "-") + f"-window-{index}"
        path = self.artifacts / f"{self.implementation}-{label}.json"
        require(
            self.identity is not None and self.readiness_completed_at is not None,
            "start must complete before measurement",
        )
        require(
            not path.exists() and not path.with_suffix(".window.json").exists(),
            "window evidence already exists",
        )
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
            self._check_postgres()
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
            self._check_postgres()
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
            result.update(self._timing(started, completed))
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
                window.update(self._timing(started, completed))
            except Exception as timing_error:
                # Invalid clocks/state must never replace the failure that stopped load.
                window["timing_error"] = f"{type(timing_error).__name__}: {timing_error}"
            self.previous_window_completed_at = completed
            try:
                path.with_suffix(".window.json").write_text(
                    json.dumps(window, indent=2) + "\n", encoding="utf-8"
                )
            except OSError:
                if failure is None:
                    raise
