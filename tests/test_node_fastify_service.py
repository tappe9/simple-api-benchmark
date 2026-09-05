#!/usr/bin/env python3
"""Focused source and Docker acceptance checks for Node.js / Fastify."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "node-fastify"
IMAGE = "node:24.20.0-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e"
DEPENDENCIES = {"fastify": "5.12.3", "pg": "8.23.0"}
DB_ENVIRONMENT = {
    "DATABASE_HOST": "postgres", "DATABASE_PORT": "5432", "DATABASE_NAME": "benchmark",
    "DATABASE_USER": "benchmark", "DATABASE_PASSWORD": "benchmark",
}


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


def check_static_contract() -> None:
    for name in (
        "package.json", "package-lock.json", "Dockerfile", ".dockerignore", ".node-version",
        "src/app.js", "src/database.js", "src/server.js", "src/healthcheck.js",
        "test/app.test.js", "test/database.test.js", "test/server.test.js", "test/healthcheck.test.js",
    ):
        require((APP / name).is_file(), f"required file is missing: apps/node-fastify/{name}")
    package = json.loads((APP / "package.json").read_text())
    lock = json.loads((APP / "package-lock.json").read_text())
    require(package["dependencies"] == DEPENDENCIES, "direct dependencies must be exactly pinned")
    require(package["engines"]["node"] == "24.20.0", "Node version is not pinned")
    require((APP / ".node-version").read_text().strip() == "24.20.0", "Node version file differs")
    require(lock["lockfileVersion"] == 3, "unexpected lockfile version")
    require(lock["packages"][""]["dependencies"] == DEPENDENCIES, "lockfile root differs")
    for name, version in DEPENDENCIES.items():
        require(lock["packages"][f"node_modules/{name}"]["version"] == version, f"unlocked {name}")
    for name, entry in lock["packages"].items():
        if name:
            require(bool(entry.get("integrity")), f"missing package integrity: {name}")
    require(not package.get("devDependencies"), "unexpected development dependency stack")

    compose = (ROOT / "docker-compose.yml").read_text()
    match = re.search(r"(?ms)^  node-fastify:\n.*?(?=^  [\w-]+:|^\S|\Z)", compose)
    require(match is not None, "node-fastify Compose service is missing")
    service = match.group()
    for expected in (
        "context: ./apps/node-fastify", "<<: *database-environment", "NODE_ENV: production",
        "postgres:", "condition: service_healthy", '"127.0.0.1:8080:8080"',
        "cpus: 1.0", "mem_limit: 512m", "- benchmark", 'restart: "no"',
        "src/healthcheck.js", "- node", "no-new-privileges:true", "- ALL",
    ):
        require(expected in service, f"missing Node Compose constraint: {expected}")
    dockerfile = (APP / "Dockerfile").read_text()
    require(f"FROM {IMAGE} AS dependencies" in dockerfile, "dependency image is not pinned")
    require(f"FROM {IMAGE} AS runtime" in dockerfile, "runtime image is not pinned")
    for expected in (
        "npm ci --omit=dev --ignore-scripts", "USER node", "ENV NODE_ENV=production",
        "EXPOSE 8080", 'ENTRYPOINT ["node"]', 'CMD ["src/server.js"]',
        "COPY --from=dependencies /app/node_modules ./node_modules", "COPY src ./src",
    ):
        require(expected in dockerfile, f"missing Docker constraint: {expected}")
    source = (APP / "src/app.js").read_text()
    compact = re.sub(r"\s+", "", source)
    require("WHERE id = $1" in source, "parameterized query is missing")
    require("returnfibonacci(n-1)+fibonacci(n-2)" in compact, "Fibonacci is not direct recursion")
    require("result:fibonacci(30)" in compact, "each CPU request must calculate Fibonacci(30)")
    require("832040" not in source, "precomputed CPU result in production code")
    database = (APP / "src/database.js").read_text()
    require(re.search(r"max:\s*10\b", database) is not None, "pool cap is missing")
    for key in DB_ENVIRONMENT:
        require(key in database, f"database setting is missing: {key}")
    require(re.search(r"(?m)^test-node-fastify:", (ROOT / "Makefile").read_text()) is not None,
            "make test-node-fastify is missing")


def request_json(path: str, status: int, expected: dict) -> None:
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:8080{path}", timeout=5)
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


def check_configuration(config: dict) -> None:
    service = config["services"]["node-fastify"]
    require(Path(service["build"]["context"]).resolve() == APP, "wrong build context")
    require(service["environment"] == {**DB_ENVIRONMENT, "NODE_ENV": "production"}, "wrong environment")
    require(service["depends_on"]["postgres"]["condition"] == "service_healthy", "DB readiness missing")
    require(float(service["cpus"]) == 1 and str(service["mem_limit"]) == "536870912", "wrong resource limits")
    require(service["restart"] == "no", "restarts must be disabled")
    require(set(service["networks"]) == {"benchmark"}, "wrong network")
    ports = service["ports"]
    require(len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1"
            and str(ports[0]["published"]) == "8080" and ports[0]["target"] == 8080,
            "port must be loopback-only 8080")
    require(service["healthcheck"]["test"] == ["CMD", "node", "src/healthcheck.js"], "wrong health check")


def check_running_service() -> str:
    container = run(["docker", "compose", "ps", "--quiet", "node-fastify"]).stdout.strip()
    require(bool(container), "Node container is missing")
    state = json.loads(run(["docker", "inspect", container]).stdout)[0]
    require(state["State"]["Health"]["Status"] == "healthy", "Node is unhealthy")
    require(state["RestartCount"] == 0, "Node restarted")
    require(state["HostConfig"]["NanoCpus"] == 1000000000, "runtime CPU limit differs")
    require(state["HostConfig"]["Memory"] == 536870912, "runtime memory limit differs")
    require(state["Config"]["User"] == "node", "runtime user is not node")
    require(state["Path"] == "node" and state["Args"] == ["src/server.js"], "extra server wrapper")
    require(not state["HostConfig"]["Privileged"], "privileged container")
    require(state["HostConfig"]["CapDrop"] == ["ALL"], "capabilities were not dropped")
    require("no-new-privileges:true" in state["HostConfig"]["SecurityOpt"], "privilege escalation allowed")
    ports = state["NetworkSettings"]["Ports"]["8080/tcp"]
    require(ports == [{"HostIp": "127.0.0.1", "HostPort": "8080"}], "runtime port is not loopback-only")
    processes = run(["docker", "top", container, "-eo", "pid,args"]).stdout.splitlines()[1:]
    commands = [line.split(maxsplit=1)[1] for line in processes if line.strip()]
    require(commands.count("node src/server.js") == 1, "not one Node server")
    run(["docker", "compose", "exec", "-T", "node-fastify", "node", "--input-type=module", "-e",
         "import assert from 'node:assert/strict'; import { existsSync } from 'node:fs'; "
         "assert.equal(process.version, 'v24.20.0'); assert.notEqual(process.getuid(), 0); "
         "assert.equal(existsSync('test'), false); "
         "assert.equal(existsSync('node_modules/.bin/tsc'), false);"])
    installed = json.loads(run([
        "docker", "compose", "exec", "-T", "node-fastify", "npm", "ls", "--omit=dev", "--depth=0", "--json",
    ]).stdout)
    require({name: data["version"] for name, data in installed["dependencies"].items()} == DEPENDENCIES,
            "runtime dependencies differ")
    return container


def check_endpoints() -> None:
    request_json("/health", 200, {"status": "ok"})
    request_json("/json", 200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})
    request_json("/db/42", 200, {"id": 42, "name": "Item 42", "price": 4200})
    request_json("/db/999", 404, {"error": "not found"})
    for value in ("invalid", "42junk", "1.0", "9223372036854775808"):
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


def check_dynamic_contract() -> None:
    project = None
    try:
        run(["npm", "ci"], cwd=APP)
        run(["npm", "test"], cwd=APP)
        run(["npm", "run", "lint"], cwd=APP)
        config = json.loads(run(["docker", "compose", "config", "--format", "json"]).stdout)
        project = config["name"]
        check_configuration(config)
        run(["docker", "compose", "up", "--detach", "--build", "--wait", "--wait-timeout", "180", "node-fastify"])
        container = check_running_service()
        check_endpoints()
        run(["docker", "compose", "stop", "--timeout", "10", "node-fastify"])
        stopped = json.loads(run(["docker", "inspect", container]).stdout)[0]
        require(stopped["State"]["ExitCode"] == 0, "Node did not shut down gracefully on SIGTERM")
        require(sql("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid();") == "0", "database connections remain after shutdown")
    finally:
        # Attempt every cleanup check even if a test or cleanup command fails.
        cleanup = run(["make", "down"], check=False)
        remaining = run(["docker", "compose", "ps", "-a", "--quiet"], check=False)
        networks = None
        if project is not None:
            networks = run(["docker", "network", "ls", "--quiet", "--filter",
                            f"label=com.docker.compose.project={project}"], check=False)
        require(cleanup.returncode == 0, "make down failed")
        require(remaining.returncode == 0 and not remaining.stdout.strip(), "project containers remain")
        if networks is not None:
            require(networks.returncode == 0 and not networks.stdout.strip(), "project networks remain")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="check source configuration without Node or Docker")
    args = parser.parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except (CheckFailure, OSError, ValueError, KeyError) as error:
        print(f"Node / Fastify acceptance check failed: {error}", file=sys.stderr)
        return 1
    print("Node / Fastify static checks passed" if args.static else "Node / Fastify acceptance checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
