#!/usr/bin/env python3
"""Acceptance checks for the Go / Gin API service."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
GO_APP = ROOT / "apps" / "go-gin"
COMPOSE_FILE = ROOT / "docker-compose.yml"
MAKEFILE = ROOT / "Makefile"
IMPLEMENTATIONS_MAKEFILE = ROOT / "benchmark" / "implementations.mk"
BASE_URL = "http://127.0.0.1:8080"


class CheckFailure(RuntimeError):
    """Raised when the Go / Gin service violates its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def run(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CheckFailure(f"required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckFailure(
            f"command timed out after {timeout}s: {' '.join(command)}"
        ) from exc

    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )

    if check and completed.returncode != 0:
        raise CheckFailure(
            f"command exited with status {completed.returncode}: {' '.join(command)}"
        )
    return completed


def check_static_contract() -> None:
    required_files = (
        GO_APP / "Dockerfile",
        GO_APP / "cmd" / "server" / "main.go",
        GO_APP / "internal" / "api" / "api.go",
        GO_APP / "internal" / "database" / "database.go",
        GO_APP / "go.mod",
        GO_APP / "go.sum",
        COMPOSE_FILE,
        MAKEFILE,
        IMPLEMENTATIONS_MAKEFILE,
    )
    for path in required_files:
        require(path.is_file(), f"required file is missing: {path.relative_to(ROOT)}")

    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  go-gin:\n.*?(?=^  [\w-]+:|^\S|\Z)", compose)
    require(match is not None, "go-gin service is missing")
    service = match.group()
    require("<<: *api-defaults" in service, "go-gin does not inherit shared API defaults")
    require("context: ./apps/go-gin" in service, "go-gin build context is incorrect")
    require("<<: *database-environment" in service, "go-gin database environment is missing")
    require("GIN_MODE: release" in service, "Gin release mode is not configured")
    require("/go-gin" in service and "healthcheck" in service, "go-gin health check is missing")

    dockerfile = (GO_APP / "Dockerfile").read_text(encoding="utf-8")
    require(
        "FROM golang:1.27.1-bookworm@sha256:648f440f42a0958804efb24df176f806f9d353b41f1c0627f666428e40310f6b AS build"
        in dockerfile,
        "Go builder image is not pinned",
    )
    require("FROM scratch" in dockerfile, "runtime image is not scratch")
    require("USER 65532:65532" in dockerfile, "runtime does not use the non-root user")
    require('ENTRYPOINT ["/go-gin"]' in dockerfile, "runtime entrypoint is incorrect")

    api_source = (GO_APP / "internal" / "api" / "api.go").read_text(encoding="utf-8")
    require("WHERE id = $1" in api_source, "database query is not parameterized")
    require(
        "returnfibonacci(n-1)+fibonacci(n-2)" in api_source.replace(" ", ""),
        "CPU implementation is not direct recursion",
    )

    database_source = (GO_APP / "internal" / "database" / "database.go").read_text(encoding="utf-8")
    require("MaxConnections int32 = 10" in database_source, "database pool maximum is not 10")

    makefile = MAKEFILE.read_text(encoding="utf-8")
    require(
        "include benchmark/implementations.mk" in makefile,
        "Makefile does not include generated implementation targets",
    )
    generated = IMPLEMENTATIONS_MAKEFILE.read_text(encoding="utf-8")
    require(
        re.search(r"(?m)^test-go-gin\s*:", generated) is not None,
        "generated Makefile target is missing: test-go-gin",
    )


def request_json(path: str, expected_status: int) -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise CheckFailure(f"request failed for {path}: {exc}") from exc

    with response:
        status = response.status
        content_type = response.headers.get("Content-Type", "")
        body = response.read()

    require(status == expected_status, f"{path} returned status {status}, want {expected_status}")
    require(
        content_type.startswith("application/json"),
        f"{path} returned Content-Type {content_type!r}",
    )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CheckFailure(f"{path} returned invalid JSON: {body!r}") from exc
    require(isinstance(payload, dict), f"{path} returned non-object JSON: {payload!r}")
    return payload


def check_endpoints() -> None:
    require(request_json("/health", 200) == {"status": "ok"}, "unexpected /health response")
    require(
        request_json("/json", 200)
        == {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]},
        "unexpected /json response",
    )
    require(
        request_json("/db/42", 200) == {"id": 42, "name": "Item 42", "price": 4200},
        "unexpected /db/42 response",
    )
    require(
        request_json("/db/999", 404) == {"error": "not found"},
        "unexpected unknown-item response",
    )
    require(
        request_json("/db/not-an-integer", 400) == {"error": "invalid id"},
        "unexpected invalid-ID response",
    )
    expected_cpu = {"input": 30, "result": 832040}
    require(request_json("/cpu", 200) == expected_cpu, "unexpected /cpu response")
    require(request_json("/cpu", 200) == expected_cpu, "repeated /cpu response changed")


def check_container_contract() -> None:
    container_id = run(["docker", "compose", "ps", "--quiet", "go-gin"]).stdout.strip()
    require(bool(container_id), "go-gin container is not running")

    state = json.loads(run(["docker", "inspect", container_id]).stdout)[0]
    require(state["State"]["Health"]["Status"] == "healthy", "Go is unhealthy")
    require(state["RestartCount"] == 0, "Go restarted")
    host = state["HostConfig"]
    require(host["NanoCpus"] == 1000000000, "runtime CPU limit differs")
    require(host["Memory"] == 536870912, "runtime memory limit differs")
    require(host["RestartPolicy"]["Name"] == "no", "restarts must be disabled")
    require(not host["Privileged"], "privileged container")
    require(host["CapDrop"] == ["ALL"], "capabilities were not dropped")
    require("no-new-privileges:true" in host["SecurityOpt"], "privilege escalation is allowed")
    require(state["Config"]["User"] == "65532:65532", "runtime user differs")
    require(state["Path"] == "/go-gin" and state["Args"] == [], "server is not the direct process")
    require(
        state["NetworkSettings"]["Ports"]["8080/tcp"]
        == [{"HostIp": "127.0.0.1", "HostPort": "8080"}],
        "runtime port is not loopback-only",
    )


def check_dynamic_contract() -> None:
    formatted = run(["gofmt", "-l", "."], cwd=GO_APP).stdout.strip()
    require(not formatted, f"Go files require formatting: {formatted}")
    run(["go", "test", "./..."], cwd=GO_APP)
    run(["go", "vet", "./..."], cwd=GO_APP)
    run(["docker", "compose", "config"])

    primary_error: BaseException | None = None
    try:
        run(
            [
                "docker",
                "compose",
                "up",
                "--detach",
                "--build",
                "--wait",
                "--wait-timeout",
                "180",
                "go-gin",
            ],
            timeout=600,
        )
        check_container_contract()
        check_endpoints()
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup = run(["make", "down"], check=False)
        remaining = run(
            ["docker", "compose", "ps", "-a", "--quiet"],
            check=False,
        )
        cleanup_error: CheckFailure | None = None
        if cleanup.returncode != 0:
            cleanup_error = CheckFailure(f"make down exited with status {cleanup.returncode}")
        elif remaining.returncode != 0:
            cleanup_error = CheckFailure(
                f"docker compose ps exited with status {remaining.returncode}"
            )
        elif remaining.stdout.strip():
            cleanup_error = CheckFailure(
                f"project containers remain after cleanup: {remaining.stdout.strip()}"
            )

        if primary_error is not None:
            if cleanup_error is not None:
                raise CheckFailure(f"{primary_error}; cleanup also failed: {cleanup_error}") from primary_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static",
        action="store_true",
        help="validate repository files without running Go or Docker",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except CheckFailure as exc:
        print(f"Go / Gin service check failed: {exc}", file=sys.stderr)
        return 1

    mode = "static contract" if args.static else "Go / Gin service"
    print(f"{mode} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
