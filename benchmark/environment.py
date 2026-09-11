"""Own one isolated Compose project and observe only its API container."""

import hashlib
import json
import os
import platform
import re
import shlex
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from .healthcheck import (
    CONTAINER_HEALTHCHECK,
    EXTERNAL_READINESS,
    override_text,
    parse_exec_events,
    require_no_exec_activity,
    require_probe_only_activity,
    validate_policy,
    wait_external_readiness,
)
from .install_oha import SHA256, VERSION, platform_asset
from .process import ROOT, execute
from .registry import active_members, implementation, implementation_ids
from .results import BenchmarkFailure, require, strict_json


def validate_state(value: dict, project: str, service: str, identity=None) -> tuple[str, str]:
    try:
        require(type(value) is dict, "container inspect must be an object")
        state = value["State"]
        require(
            state["Running"] is True
            and state["Restarting"] is False
            and state["Dead"] is False
            and state["OOMKilled"] is False
            and state["Status"] == "running",
            "container exited, restarted or was OOM-killed",
        )
        require(
            type(value["RestartCount"]) is int and value["RestartCount"] == 0,
            "container restart detected",
        )
        limits = value["HostConfig"]
        require(
            type(limits["NanoCpus"]) is int and limits["NanoCpus"] == 1000000000,
            "API must have exactly 1 CPU",
        )
        require(
            type(limits["Memory"]) is int and limits["Memory"] == 536870912,
            "API must have exactly 512 MiB",
        )
        require(limits["RestartPolicy"]["Name"] == "no", "API restart policy must be no")
        labels = value["Config"]["Labels"]
        require(
            labels["com.docker.compose.project"] == project
            and labels["com.docker.compose.service"] == service,
            "container does not belong to this project's API service",
        )
        require(
            type(value["Id"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["Id"]) is not None,
            "missing full container ID",
        )
        started = state["StartedAt"]
        require(
            type(started) is str and bool(started) and started.endswith("Z"),
            "missing container start time",
        )
        current = (value["Id"], started)
        require(
            identity is None or current == identity,
            "container identity/start time changed (exit/restart)",
        )
        return current
    except (KeyError, TypeError) as error:
        raise BenchmarkFailure(f"incomplete container state: {error}") from error


def memory_bytes(raw: str, container: str) -> int:
    """Docker CLI Linux memory excludes inactive file cache; units are binary.

    Docker rounds its text values. Round conversion up to a whole byte and record
    this observed/rounded sampling method, not a kernel high-water or RSS metric.
    """
    data = strict_json(raw.encode())
    require(
        type(data) is dict and data.get("ID") == container,
        "memory sample belongs to wrong/missing container",
    )
    text = data.get("MemUsage")
    require(type(text) is str, "memory sample has no MemUsage string")
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(B|KiB|MiB|GiB) / ([0-9]+(?:\.[0-9]+)?)(B|KiB|MiB|GiB)", text
    )
    require(match is not None, f"unrecognized Docker memory value/unit: {text!r}")
    units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    usage = int((Decimal(match[1]) * units[match[2]]).to_integral_value(rounding=ROUND_CEILING))
    limit = Decimal(match[3]) * units[match[4]]
    require(limit == 536870912 and 0 < usage <= limit, "invalid memory sample or API memory limit")
    return usage


def validate_processes(state: dict, output: str, *, allow_health_probe: bool = True) -> None:
    """Count OS processes, not framework threads, using the same rule for all APIs."""

    def normalized(arguments):
        require(bool(arguments), "empty container process command")
        return [Path(arguments[0]).name, *arguments[1:]]

    server = normalized([state["Path"], *state["Args"]])
    allowed = (server,)
    if allow_health_probe:
        probe = state["Config"]["Healthcheck"]["Test"]
        require(probe[0] == "CMD", "expected a direct, separately identifiable health probe")
        allowed = (server, normalized(probe[1:]))
    rows = output.strip().splitlines()
    require(bool(rows) and "PID" in rows[0], "container process list unavailable")
    commands = []
    for row in rows[1:]:
        pieces = row.strip().split(None, 1)
        require(len(pieces) == 2 and pieces[0].isdigit(), "invalid process list row")
        commands.append(normalized(shlex.split(pieces[1])))
    require(
        commands.count(server) == 1 and all(command in allowed for command in commands),
        (
            "expected one server process and only independent health probes"
            if allow_health_probe
            else "expected exactly one server process"
        ),
    )


def registered_pinned_versions() -> dict:
    """Extract every implemented stack without changing official cohort membership."""

    def read(path):
        identifier, _, filename = path.partition("/")
        return (ROOT / implementation(identifier)["source_path"] / filename).read_text(
            encoding="utf-8"
        )

    def match(pattern, text):
        found = re.findall(pattern, text, re.MULTILINE)
        require(len(found) == 1, f"cannot identify pinned version using {pattern}")
        return found[0]

    go = read("go-gin/go.mod")
    go_echo = read("go-echo/go.mod")
    rust = read("rust-actix/Cargo.toml")
    axum = read("rust-axum/Cargo.toml")
    node = strict_json(read("node-fastify/package.json").encode())
    python = dict(
        re.findall(r"^([a-z]+)==([0-9.]+)$", read("python-fastapi/requirements.in"), re.MULTILINE)
    )
    versions = {
        "go-gin": {
            "go": match(r"^toolchain go([0-9.]+)$", go),
            "gin": match(r"github.com/gin-gonic/gin v([0-9.]+)", go),
            "pgx": match(r"github.com/jackc/pgx/v5 v([0-9.]+)", go),
        },
        "go-echo": {
            "go": match(r"^toolchain go([0-9.]+)$", go_echo),
            "echo": match(r"github.com/labstack/echo/v5 v([0-9.]+)", go_echo),
            "pgx": match(r"github.com/jackc/pgx/v5 v([0-9.]+)", go_echo),
        },
        "rust-actix": {
            "rust": match(r'^channel = "([0-9.]+)"$', read("rust-actix/rust-toolchain.toml")),
            **{
                name: match(r"^" + name + r' = .*version = "=([0-9.]+)"', rust)
                for name in ("actix-web", "sqlx", "serde")
            },
            "serde_json": match(r'^serde_json = "=([0-9.]+)"$', rust),
        },
        "rust-axum": {
            "rust": match(r'^channel = "([0-9.]+)"$', read("rust-axum/rust-toolchain.toml")),
            **{
                name: match(r"^" + name + r' = .*version = "=([0-9.]+)"', axum)
                for name in ("axum", "tokio", "sqlx", "serde")
            },
            "serde_json": match(r'^serde_json = "=([0-9.]+)"$', axum),
        },
        "node-fastify": {"node": node["engines"]["node"], **node["dependencies"]},
        "python-fastapi": {"python": read("python-fastapi/.python-version").strip(), **python},
    }
    require(
        set(versions) == set(implementation_ids()),
        "version extractors must cover registered implementations",
    )
    for identifier, values in versions.items():
        require(
            set(implementation(identifier)["version_fields"]) <= set(values),
            "missing required stack versions",
        )
        require(
            all(
                type(value) is str and re.fullmatch(r"\d+\.\d+\.\d+", value)
                for value in values.values()
            ),
            f"unrecognized pinned versions for {identifier}",
        )
    return versions


def pinned_versions() -> dict:
    """Keep official report metadata limited to the complete active cohort."""
    versions = registered_pinned_versions()
    return {identifier: versions[identifier] for identifier in active_members()}


def provenance(oha: Path) -> dict:
    dirty = execute(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            ".",
            ":(exclude)results/latest.json",
        ],
        timeout=30,
    )
    require(not dirty.strip(), f"commit source changes before benchmarking:\n{dirty}")
    commit = execute(["git", "rev-parse", "HEAD"], timeout=10).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "source commit unavailable")
    endpoint = os.environ.get("DOCKER_HOST")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        context = strict_json(execute(["docker", "context", "inspect"], timeout=10).encode())
        require(type(context) is list and len(context) == 1, "Docker context unavailable")
        endpoint = context[0]["Endpoints"]["docker"]["Host"]
    require(
        endpoint.startswith("unix://"),
        "benchmark requires a local Unix-socket Docker daemon, not a remote context",
    )
    info = strict_json(execute(["docker", "info", "--format", "{{json .}}"], timeout=15).encode())
    require(info.get("OSType") == "linux", "Linux API containers are required")
    return {
        "source_commit": commit,
        "source_tree": execute(["git", "rev-parse", "HEAD^{tree}"], timeout=10).strip(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "host_cpu_count": os.cpu_count(),
        "docker": {
            key: info[key]
            for key in (
                "ServerVersion",
                "OperatingSystem",
                "Architecture",
                "NCPU",
                "MemTotal",
                "KernelVersion",
            )
        },
        "oha": {"version": VERSION, "asset": platform_asset(), "sha256": SHA256[platform_asset()]},
        "versions": pinned_versions(),
        "lock_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for pattern in (
                "apps/*/go.sum",
                "apps/*/Cargo.lock",
                "apps/*/package-lock.json",
                "apps/*/requirements.lock",
            )
            for path in ROOT.glob(pattern)
        },
        "memory_method": "Maximum observed docker stats --no-stream API MemUsage; binary units rounded by Docker, inactive file cache excluded. Samples run sequentially with state checks; not kernel high-water RSS.",
        "oha_duration_method": "-z sends for the specified duration; -w drains in-flight requests with a 15s request timeout. Throughput uses oha total elapsed seconds, including drain.",
    }


class DockerEnvironment:
    def __init__(
        self,
        oha: Path,
        artifacts: Path,
        *,
        compose: str = "docker compose",
        connections: int = 50,
        request_timeout: int = 15,
        health_policy: str = CONTAINER_HEALTHCHECK,
        audit_health_events: bool = False,
    ):
        self.project = "sab-benchmark-" + uuid.uuid4().hex[:12]
        executable = shlex.split(compose)
        require(
            len(executable) == 2
            and Path(executable[0]).name == "docker"
            and executable[1] == "compose",
            "use docker compose without context or project overrides",
        )
        require(type(audit_health_events) is bool, "health event audit flag must be boolean")
        self.prefix = executable + ["-f", str(ROOT / "docker-compose.yml"), "-p", self.project]
        self.artifacts = artifacts / self.project
        self.artifacts.mkdir(parents=True)
        self.oha = oha
        self.connections = connections
        self.request_timeout = request_timeout
        self.health_policy = validate_policy(health_policy)
        self.audit_health_events = audit_health_events
        self.container = None
        self.identity = None
        self.implementation = None
        self.readiness = None
        self.probe_command = None
        print(
            f"Owned Compose project: {self.project}; raw diagnostics: {self.artifacts}", flush=True
        )

    def build(self, implementation: str) -> None:
        self.implementation = implementation
        output = execute(self.prefix + ["build", implementation], timeout=900)
        (self.artifacts / f"{implementation}-build.log").write_text(output)

    def inspect(self) -> dict:
        data = strict_json(execute(["docker", "inspect", self.container], timeout=10).encode())
        require(type(data) is list and len(data) == 1, "API container inspect missing")
        return data[0]

    def start(self, implementation: str) -> dict:
        self.implementation = implementation
        runtime_prefix = self.prefix
        baseline_readiness_started = None
        if self.health_policy == EXTERNAL_READINESS:
            override = self.artifacts / f"{implementation}-external-readiness.compose.yml"
            override.write_text(override_text(implementation), encoding="utf-8")
            runtime_prefix = self.prefix[:-2] + ["-f", str(override), *self.prefix[-2:]]
            execute(
                runtime_prefix + ["up", "--detach", "--wait", "--wait-timeout", "60", "postgres"],
                timeout=120,
            )
            execute(runtime_prefix + ["up", "--detach", implementation], timeout=120)
        else:
            if self.audit_health_events:
                baseline_readiness_started = datetime.now(timezone.utc)
            execute(
                runtime_prefix
                + ["up", "--detach", "--wait", "--wait-timeout", "60", implementation],
                timeout=120,
            )
        self.container = execute(
            runtime_prefix + ["ps", "--quiet", implementation], timeout=10
        ).strip()
        require(
            re.fullmatch(r"[0-9a-f]{64}", self.container) is not None,
            "expected one full API container ID",
        )
        state = self.inspect()
        self.identity = validate_state(state, self.project, implementation)
        if self.health_policy == EXTERNAL_READINESS:
            healthcheck = state["Config"].get("Healthcheck")
            require(
                type(healthcheck) is dict and healthcheck.get("Test") == ["NONE"],
                "measured API healthcheck must be disabled",
            )
            self.probe_command = None
            self.readiness = wait_external_readiness(
                "http://127.0.0.1:8080",
                implementation,
                self.check,
                timeout_seconds=60.0,
                request_timeout=min(float(self.request_timeout), 2.0),
            )
        else:
            require(
                state["State"].get("Health", {}).get("Status") == "healthy",
                "API readiness was not healthy",
            )
            probe = state["Config"]["Healthcheck"]["Test"]
            require(probe[0] == "CMD" and len(probe) > 1, "API health probe command unavailable")
            self.probe_command = probe[1:]
            if self.audit_health_events:
                readiness_completed = datetime.now(timezone.utc)
                readiness_events = self.probe_events(
                    baseline_readiness_started,
                    readiness_completed,
                )
                self.readiness = {
                    "attempts": readiness_events["probe_execs"],
                    "duration_seconds": max(
                        0.0,
                        (readiness_completed - baseline_readiness_started).total_seconds(),
                    ),
                }
        validate_processes(
            state,
            execute(["docker", "top", self.container, "-eo", "pid,args"], timeout=10),
            allow_health_probe=self.health_policy == CONTAINER_HEALTHCHECK,
        )
        pg_version = execute(
            runtime_prefix
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-U",
                "benchmark",
                "-d",
                "benchmark",
                "-At",
                "-c",
                "SELECT version();",
            ],
            timeout=15,
        ).strip()
        require(pg_version.startswith("PostgreSQL "), "PostgreSQL version collection failed")
        return {
            "id": self.container,
            "image_id": state["Image"],
            "command": [state["Path"], *state["Args"]],
            "postgresql_version": pg_version,
        }

    def check(self) -> None:
        validate_state(self.inspect(), self.project, self.implementation, self.identity)

    def probe_events(self, started_at: datetime, completed_at: datetime) -> dict:
        require(
            self.audit_health_events and self.container is not None,
            "health event audit is not enabled for an owned API container",
        )
        require(
            started_at.tzinfo is not None
            and completed_at.tzinfo is not None
            and completed_at >= started_at,
            "invalid health event audit interval",
        )

        def timestamp(value: datetime) -> str:
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        def epoch_ns(value: datetime) -> int:
            utc = value.astimezone(timezone.utc)
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            delta = utc - epoch
            return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000

        exact_started_ns = epoch_ns(started_at)
        exact_completed_ns = epoch_ns(completed_at)
        query_started = started_at - timedelta(seconds=5)
        command = [
            "docker",
            "events",
            "--since",
            timestamp(query_started),
            "--until",
            timestamp(completed_at),
            "--filter",
            "type=container",
            "--filter",
            "container=" + self.container,
            "--filter",
            "event=exec_create",
            "--filter",
            "event=exec_start",
            "--filter",
            "event=exec_die",
            "--format",
            "{{json .}}",
        ]
        raw = execute(command, timeout=10)
        encoded = raw.encode()
        require(len(encoded) <= 512 * 1024, "Docker event window is oversized")
        evidence = self.artifacts / (
            f"{self.implementation}-events-{exact_started_ns}-{exact_completed_ns}.jsonl"
        )
        evidence.write_bytes(encoded)
        summary = parse_exec_events(
            encoded,
            container_id=self.container,
            probe_command=self.probe_command,
            max_events=128,
            window_started_ns=exact_started_ns,
            window_completed_ns=exact_completed_ns,
        )
        if self.health_policy == CONTAINER_HEALTHCHECK:
            require_probe_only_activity(summary)
        else:
            require_no_exec_activity(summary)
        return summary

    def measure(self, endpoint: str, duration: int, index: int) -> dict:
        from .results import parse_oha

        self.check()
        label = endpoint.strip("/").replace("/", "-") + (
            "-warmup" if index == 0 else f"-run-{index}"
        )
        path = self.artifacts / f"{self.implementation}-{label}.json"
        samples = []
        print(
            f"[{self.implementation}] {endpoint} {'warmup' if index == 0 else f'run {index}/3'}: {duration}s, {self.connections} connections",
            flush=True,
        )
        interval_started = datetime.now(timezone.utc) if self.audit_health_events else None
        with path.with_suffix(".memory.jsonl").open("w", encoding="utf-8") as log:

            def sample():
                self.check()
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
                value = memory_bytes(raw, self.container)
                samples.append(value)
                log.write(
                    json.dumps(
                        {
                            "at": datetime.now(timezone.utc).isoformat(),
                            "bytes": value,
                            "container_id": self.container,
                        }
                    )
                    + "\n"
                )
                log.flush()

            execute(
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
        interval_completed = datetime.now(timezone.utc) if self.audit_health_events else None
        event_summary = None
        if self.audit_health_events:
            event_summary = self.probe_events(interval_started, interval_completed)
        self.check()
        require(bool(samples), "memory collection produced no samples")
        require(
            path.is_file() and path.stat().st_size <= 1024 * 1024, "oha result missing or oversized"
        )
        result = parse_oha(
            path.read_bytes(), duration=duration, request_timeout=self.request_timeout
        )
        result.update(
            run=max(index, 1), peak_memory_bytes=max(samples), memory_samples=len(samples)
        )
        if event_summary is not None:
            result["health_probe_events"] = event_summary
        print(
            f"[{self.implementation}] {label}: {result['requests_per_second']:.3f} requests/s; {len(samples)} API memory samples",
            flush=True,
        )
        return result

    def cleanup(self) -> None:
        execute(
            self.prefix + ["down", "--remove-orphans", "--volumes", "--timeout", "10"], timeout=60
        )
        for arguments in (["ps", "-aq"], ["network", "ls", "-q"], ["volume", "ls", "-q"]):
            remaining = execute(
                [
                    "docker",
                    *arguments,
                    "--filter",
                    "label=com.docker.compose.project=" + self.project,
                ],
                timeout=10,
            )
            require(
                not remaining.strip(), f"cleanup left resources for {self.project}: {remaining}"
            )
        self.container = None
        self.identity = None
        self.implementation = None
        self.readiness = None
        self.probe_command = None
