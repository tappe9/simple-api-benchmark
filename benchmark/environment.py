"""Own one isolated Compose project and observe only its API container."""

import hashlib
import json
import os
import platform
import re
import shlex
import uuid
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from .install_oha import SHA256, VERSION, platform_asset
from .process import ROOT, execute
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


def validate_processes(state: dict, output: str) -> None:
    """Count OS processes, not framework threads, using the same rule for all APIs."""

    def normalized(arguments):
        require(bool(arguments), "empty container process command")
        return [Path(arguments[0]).name, *arguments[1:]]

    server = normalized([state["Path"], *state["Args"]])
    probe = state["Config"]["Healthcheck"]["Test"]
    require(probe[0] == "CMD", "expected a direct, separately identifiable health probe")
    probe = normalized(probe[1:])
    rows = output.strip().splitlines()
    require(bool(rows) and "PID" in rows[0], "container process list unavailable")
    commands = []
    for row in rows[1:]:
        pieces = row.strip().split(None, 1)
        require(len(pieces) == 2 and pieces[0].isdigit(), "invalid process list row")
        commands.append(normalized(shlex.split(pieces[1])))
    require(
        commands.count(server) == 1 and all(command in (server, probe) for command in commands),
        "expected one server process and only independent health probes",
    )


def pinned_versions() -> dict:
    def read(path):
        return (ROOT / "apps" / path).read_text(encoding="utf-8")

    def match(pattern, text):
        found = re.findall(pattern, text, re.MULTILINE)
        require(len(found) == 1, f"cannot identify pinned version using {pattern}")
        return found[0]

    go = read("go-gin/go.mod")
    rust = read("rust-actix/Cargo.toml")
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
        "rust-actix": {
            "rust": match(r'^channel = "([0-9.]+)"$', read("rust-actix/rust-toolchain.toml")),
            **{
                name: match(r"^" + name + r' = .*version = "=([0-9.]+)"', rust)
                for name in ("actix-web", "sqlx", "serde")
            },
            "serde_json": match(r'^serde_json = "=([0-9.]+)"$', rust),
        },
        "node-fastify": {"node": node["engines"]["node"], **node["dependencies"]},
        "python-fastapi": {"python": read("python-fastapi/.python-version").strip(), **python},
    }
    for implementation, values in versions.items():
        require(
            all(
                type(value) is str and re.fullmatch(r"\d+\.\d+\.\d+", value)
                for value in values.values()
            ),
            f"unrecognized pinned versions for {implementation}",
        )
    return versions


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
    # HTTP always targets host loopback. A remote daemon would measure the wrong host.
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
    ):
        self.project = "sab-benchmark-" + uuid.uuid4().hex[:12]
        executable = shlex.split(compose)
        require(
            len(executable) == 2
            and Path(executable[0]).name == "docker"
            and executable[1] == "compose",
            "use docker compose without context or project overrides",
        )
        self.prefix = executable + ["-f", str(ROOT / "docker-compose.yml"), "-p", self.project]
        self.artifacts = artifacts / self.project
        self.artifacts.mkdir(parents=True)
        self.oha = oha
        self.connections = connections
        self.request_timeout = request_timeout
        self.container = None
        self.identity = None
        self.implementation = None
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
        execute(
            self.prefix + ["up", "--detach", "--wait", "--wait-timeout", "60", implementation],
            timeout=120,
        )
        self.container = execute(
            self.prefix + ["ps", "--quiet", implementation], timeout=10
        ).strip()
        require(
            re.fullmatch(r"[0-9a-f]{64}", self.container) is not None,
            "expected one full API container ID",
        )
        state = self.inspect()
        self.identity = validate_state(state, self.project, implementation)
        require(
            state["State"].get("Health", {}).get("Status") == "healthy",
            "API readiness was not healthy",
        )
        validate_processes(
            state, execute(["docker", "top", self.container, "-eo", "pid,args"], timeout=10)
        )
        pg_version = execute(
            self.prefix
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
