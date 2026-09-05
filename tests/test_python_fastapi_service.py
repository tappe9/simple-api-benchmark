#!/usr/bin/env python3
"""Focused source, pytest, and Docker acceptance checks for Python / FastAPI."""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "python-fastapi"
IMAGE = "python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f"
DEPENDENCIES = {"fastapi": "0.141.1", "uvicorn": "0.52.4", "asyncpg": "0.31.0"}
DB_ENVIRONMENT = {
    "DATABASE_HOST": "postgres", "DATABASE_PORT": "5432", "DATABASE_NAME": "benchmark",
    "DATABASE_USER": "benchmark", "DATABASE_PASSWORD": "benchmark",
}
SERVER_ARGS = [
    "-m", "uvicorn", "benchmark_api.app:app", "--host", "0.0.0.0", "--port", "8080",
    "--workers", "1", "--loop", "asyncio", "--http", "h11", "--no-access-log",
    "--timeout-graceful-shutdown", "5",
]


class CheckFailure(RuntimeError):
    """A service acceptance requirement was not met."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 600,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise CheckFailure(f"could not run {command[0]}: {error}") from error
    for output, stream in ((result.stdout, sys.stdout), (result.stderr, sys.stderr)):
        if output:
            print(output, end="" if output.endswith("\n") else "\n", file=stream)
    if check:
        require(result.returncode == 0, f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def lock_versions(path: Path) -> dict[str, str]:
    versions = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith(("#", "-r ")):
            continue
        match = re.fullmatch(r"([a-z0-9-]+)==([0-9]+(?:\.[0-9]+)+)(?: --hash=sha256:[0-9a-f]{64})+", line)
        require(match is not None, f"unlocked dependency in {path.name}")
        name, version = match.group(1, 2)
        require(name not in versions, f"duplicate lock entry: {name}")
        versions[name] = version
    require(bool(versions), f"empty dependency lock: {path.name}")
    return versions


def check_static_contract() -> None:
    for name in (
        ".python-version", "requirements.in", "requirements-dev.in", "requirements.lock",
        "requirements-dev.lock", "pyproject.toml", "Dockerfile", ".dockerignore",
        "benchmark_api/app.py", "benchmark_api/database.py", "benchmark_api/healthcheck.py",
        "tests/test_api.py", "tests/test_database.py", "tests/test_healthcheck.py",
    ):
        require((APP / name).is_file(), f"required file is missing: apps/python-fastapi/{name}")
    require((APP / ".python-version").read_text().strip() == "3.14.7", "Python version differs")
    runtime = lock_versions(APP / "requirements.lock")
    development = lock_versions(APP / "requirements-dev.lock")
    require({name: runtime[name] for name in DEPENDENCIES} == DEPENDENCIES, "runtime pins differ")
    require(set((APP / "requirements.in").read_text().splitlines())
            == {f"{name}=={version}" for name, version in DEPENDENCIES.items()}, "input pins differ")
    require("-r requirements.lock" in (APP / "requirements-dev.lock").read_text(), "runtime lock not reused")
    require(development["pytest"] == "9.1.1" and development["ruff"] == "0.16.5", "test tools unpinned")
    dockerfile = (APP / "Dockerfile").read_text()
    require(dockerfile.count(f"FROM {IMAGE}") == 2, "base images must be exactly pinned")
    for expected in (
        "--require-hashes --only-binary=:all:", "USER 10001:10001", "EXPOSE 8080",
        'ENTRYPOINT ["python", "-m", "uvicorn"]', '"--workers", "1"',
        '"--loop", "asyncio"', '"--http", "h11"', "COPY benchmark_api ./benchmark_api",
    ):
        require(expected in dockerfile, f"missing Docker constraint: {expected}")
    source = (APP / "benchmark_api/app.py").read_text()
    compact = re.sub(r"\s+", "", source)
    require("WHERE id = $1" in source, "parameterized query is missing")
    require("returnfibonacci(n-1)+fibonacci(n-2)" in compact, "Fibonacci is not direct recursion")
    require('"result":fibonacci(30)' in compact, "CPU request does not calculate Fibonacci(30)")
    require("832040" not in source, "precomputed result in production source")
    require("lru_cache" not in source and "@cache" not in source, "cached CPU calculation")
    require('"max_size": 10' in (APP / "benchmark_api/database.py").read_text(), "pool cap is missing")
    compose = (ROOT / "docker-compose.yml").read_text()
    match = re.search(r"(?ms)^  python-fastapi:\n.*?(?=^  [\w-]+:|^\S|\Z)", compose)
    require(match is not None, "Python Compose service is missing")
    for expected in ("<<: *database-environment", "condition: service_healthy", "cpus: 1.0",
                     "mem_limit: 512m", '"127.0.0.1:8080:8080"', 'restart: "no"'):
        require(expected in match.group(), f"missing Compose constraint: {expected}")
    require("test-python-fastapi:" in (ROOT / "Makefile").read_text(), "Make target is missing")


def check_configuration(config: dict) -> None:
    service = config["services"]["python-fastapi"]
    require(Path(service["build"]["context"]).resolve() == APP, "wrong build context")
    require(service["environment"] == DB_ENVIRONMENT, "shared database environment differs")
    require(service["depends_on"]["postgres"]["condition"] == "service_healthy", "DB readiness missing")
    require(float(service["cpus"]) == 1 and str(service["mem_limit"]) == "536870912", "wrong resource limits")
    require(service["restart"] == "no", "restarts must be disabled")
    require(set(service["networks"]) == {"benchmark"}, "wrong network")
    ports = service["ports"]
    require(len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1"
            and str(ports[0]["published"]) == "8080" and ports[0]["target"] == 8080,
            "port must be loopback-only 8080")
    require(service["healthcheck"]["test"] == ["CMD", "python", "-m", "benchmark_api.healthcheck"],
            "wrong health check")


def check_server_processes(commands: list[str]) -> None:
    servers = [command for command in commands if "uvicorn" in command or "multiprocessing" in command]
    require(servers == ["python " + " ".join(SERVER_ARGS)], "not exactly one direct Uvicorn worker")


def request_json(path: str, status: int, expected: dict) -> None:
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:8080{path}", timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        require(response.status == status, f"{path}: unexpected HTTP status {response.status}")
        require(response.headers.get_content_type() == "application/json", f"{path}: not JSON")
        payload = json.load(response)
    require(payload == expected, f"{path}: unexpected response {payload!r}")
    for key, value in expected.items():
        require(type(payload[key]) is type(value), f"{path}: wrong JSON type for {key}")
        if isinstance(value, list):
            require(all(type(item) is int for item in payload[key]), f"{path}: wrong array types")


def sql(statement: str) -> str:
    return run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-X", "-U", "benchmark",
        "-d", "benchmark", "-v", "ON_ERROR_STOP=1", "-Atc", statement,
    ]).stdout.strip()


def check_focused_tests() -> None:
    require(sys.version_info[:3] == (3, 14, 7), "acceptance requires Python 3.14.7")
    with tempfile.TemporaryDirectory(prefix="python-fastapi-tests-") as directory:
        run([sys.executable, "-m", "venv", directory])
        python = str(Path(directory) / "bin" / "python")
        run([python, "-m", "pip", "install", "--require-hashes", "--only-binary=:all:",
             "-r", "requirements-dev.lock"], cwd=APP)
        run([python, "-m", "pip", "check"], cwd=APP)
        run([python, "-m", "ruff", "check", "."], cwd=APP)
        run([python, "-m", "ruff", "check", "--config", str(APP / "pyproject.toml"),
             "tests/test_python_fastapi_service.py", "tests/test_python_fastapi_acceptance.py"])
        run([python, "-m", "compileall", "-q", "benchmark_api", "tests"], cwd=APP)
        run([python, "-m", "pytest", "-q"], cwd=APP)


def check_running_service() -> str:
    container = run(["docker", "compose", "ps", "--quiet", "python-fastapi"]).stdout.strip()
    require(bool(container), "Python container is missing")
    state = json.loads(run(["docker", "inspect", container]).stdout)[0]
    require(state["State"]["Health"]["Status"] == "healthy", "Python is unhealthy")
    require(state["RestartCount"] == 0, "Python restarted")
    require(state["HostConfig"]["RestartPolicy"]["Name"] == "no", "runtime restart policy differs")
    require(state["HostConfig"]["NanoCpus"] == 1000000000, "runtime CPU limit differs")
    require(state["HostConfig"]["Memory"] == 536870912, "runtime memory limit differs")
    require(state["Config"]["User"] == "10001:10001", "runtime user differs")
    require(state["Path"] == "python" and state["Args"] == SERVER_ARGS, "extra server wrapper or workers")
    require(not state["HostConfig"]["Privileged"], "privileged container")
    require(state["HostConfig"]["CapDrop"] == ["ALL"], "capabilities were not dropped")
    require("no-new-privileges:true" in state["HostConfig"]["SecurityOpt"], "privilege escalation allowed")
    require(state["NetworkSettings"]["Ports"]["8080/tcp"]
            == [{"HostIp": "127.0.0.1", "HostPort": "8080"}], "runtime port is not loopback-only")
    processes = run(["docker", "top", container, "-eo", "pid,args"]).stdout.splitlines()[1:]
    check_server_processes([line.split(maxsplit=1)[1] for line in processes if line.strip()])
    versions = lock_versions(APP / "requirements.lock")
    program = (
        "import importlib.metadata as m, os, pathlib, sys; "
        "assert sys.version_info[:3] == (3, 14, 7); assert os.getuid() == 10001; "
        "assert not pathlib.Path('tests').exists(); "
        f"expected = {versions!r}; "
        "assert all(m.version(name) == version for name, version in expected.items()); "
        "installed = {d.metadata['Name'].lower().replace('_', '-') for d in m.distributions()}; "
        "assert not installed.intersection({'pytest', 'ruff', 'httpx2'}); "
        "print('Production runtime versions and non-root user verified')"
    )
    run(["docker", "compose", "exec", "-T", "python-fastapi", "python", "-c", program])
    run(["docker", "compose", "exec", "-T", "python-fastapi", "python", "-c",
         "import asyncio\nfrom benchmark_api.database import open_pool, close_pool\n"
         "async def check():\n    pool = await open_pool()\n    try:\n"
         "        assert pool.get_max_size() == 10\n        assert pool.get_min_size() == 1\n"
         "        assert await pool.fetchval('SELECT 1') == 1\n    finally:\n"
         "        await close_pool(pool)\nasyncio.run(check())"])
    return container


def check_endpoints() -> None:
    request_json("/health", 200, {"status": "ok"})
    request_json("/json", 200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})
    for value in ("42", "+42", "00042"):
        request_json(f"/db/{value}", 200, {"id": 42, "name": "Item 42", "price": 4200})
    request_json("/db/999", 404, {"error": "not found"})
    for value in ("invalid", "42junk", "1.0", "1e2", "0x2a", "1_000", "%2042", "42%20",
                  "%EF%BC%94%EF%BC%92", "42%27%20OR%201%3D1",
                  "9223372036854775808", "-9223372036854775809"):
        request_json(f"/db/{value}", 400, {"error": "invalid id"})
    for _ in range(2):
        request_json("/cpu", 200, {"input": 30, "result": 832040})
    sql("UPDATE items SET name = 'Updated Item', price = 7 WHERE id = 42;")
    request_json("/db/42", 200, {"id": 42, "name": "Updated Item", "price": 7})
    for value in (9007199254740993, 9223372036854775807, -9223372036854775808):
        sql(f"INSERT INTO items VALUES ({value}, 'Boundary item', 1);")
        request_json(f"/db/{value}", 200, {"id": value, "name": "Boundary item", "price": 1})
    sql("DROP TABLE items;")
    request_json("/db/42", 500, {"error": "internal server error"})
    request_json("/db/invalid", 400, {"error": "invalid id"})


def check_startup_failure() -> None:
    result = run(["docker", "compose", "run", "--rm", "--no-deps", "-e", "DATABASE_PORT=1",
                  "python-fastapi"], timeout=30, check=False)
    require(result.returncode != 0, "server accepted an unavailable database")
    output = result.stdout + result.stderr
    require("database startup failed" in output, "startup error was not sanitized")
    require("Uvicorn running" not in output, "server listened before database readiness")


def check_shutdown(container: str) -> None:
    run(["docker", "compose", "stop", "--timeout", "15", "python-fastapi"])
    stopped = json.loads(run(["docker", "inspect", container]).stdout)[0]
    # Uvicorn may re-raise SIGTERM after its lifespan shutdown has completed.
    require(stopped["State"]["ExitCode"] in (0, 128 + signal.SIGTERM), "server did not stop gracefully")
    require(not stopped["State"]["OOMKilled"], "server was killed by its memory limit")
    logs = run(["docker", "compose", "logs", "--no-color", "python-fastapi"]).stdout
    require("Application shutdown complete." in logs, "lifespan shutdown did not finish")
    require("database shutdown failed" not in logs, "pool shutdown failed")
    require(sql("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid();") == "0", "database connections remain after shutdown")


def check_dynamic_contract() -> None:
    project = None
    try:
        check_focused_tests()
        config = json.loads(run(["docker", "compose", "config", "--format", "json"]).stdout)
        project = config["name"]
        check_configuration(config)
        run(["docker", "compose", "up", "--detach", "--build", "--wait", "--wait-timeout", "180", "python-fastapi"])
        container = check_running_service()
        check_endpoints()
        check_startup_failure()
        check_shutdown(container)
    finally:
        # Attempt all cleanup checks even when an earlier check fails.
        cleanup = run(["make", "down"], check=False)
        remaining = run(["docker", "compose", "ps", "-a", "--quiet"], check=False)
        networks = None
        if project is not None:
            networks = run(["docker", "network", "ls", "--quiet", "--filter",
                            f"label=com.docker.compose.project={project}"], check=False)
        whitespace = run(["git", "diff", "--check"], check=False)
        require(cleanup.returncode == 0, "make down failed")
        require(remaining.returncode == 0 and not remaining.stdout.strip(), "project containers remain")
        if networks is not None:
            require(networks.returncode == 0 and not networks.stdout.strip(), "project networks remain")
        require(whitespace.returncode == 0, "git diff --check failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="check source without Python dependencies or Docker")
    args = parser.parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except (CheckFailure, OSError, ValueError, KeyError) as error:
        print(f"Python / FastAPI acceptance check failed: {error}", file=sys.stderr)
        return 1
    print("Python / FastAPI static checks passed" if args.static else "Python / FastAPI acceptance checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
