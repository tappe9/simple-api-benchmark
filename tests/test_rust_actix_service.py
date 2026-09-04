#!/usr/bin/env python3
"""Acceptance checks for the Rust / Actix Web API service."""

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
RUST_APP = ROOT / "apps" / "rust-actix"
COMPOSE_FILE = ROOT / "docker-compose.yml"
MAKEFILE = ROOT / "Makefile"
BASE_URL = "http://127.0.0.1:8080"


class CheckFailure(RuntimeError):
    """Raised when the Rust / Actix Web service violates its contract."""


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


def compose_service_block(compose: str, service: str) -> str:
    lines = compose.splitlines()
    marker = f"  {service}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise CheckFailure(f"Compose service is missing: {service}") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            end = index
            break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            end = index
            break
    return "\n".join(lines[start:end])


def check_static_contract() -> None:
    required_files = (
        RUST_APP / "Cargo.toml",
        RUST_APP / "Cargo.lock",
        RUST_APP / "rust-toolchain.toml",
        RUST_APP / "Dockerfile",
        RUST_APP / "src" / "lib.rs",
        RUST_APP / "src" / "main.rs",
        RUST_APP / "src" / "api.rs",
        RUST_APP / "src" / "database.rs",
        RUST_APP / "src" / "healthcheck.rs",
        RUST_APP / "src" / "item.rs",
        COMPOSE_FILE,
        MAKEFILE,
    )
    for path in required_files:
        require(path.is_file(), f"required file is missing: {path.relative_to(ROOT)}")

    manifest = (RUST_APP / "Cargo.toml").read_text(encoding="utf-8")
    for dependency in (
        'actix-web = { version = "=4.15.0"',
        'serde = { version = "=1.0.228"',
        'serde_json = "=1.0.145"',
        'sqlx = { version = "=0.9.0"',
    ):
        require(dependency in manifest, f"dependency is not pinned: {dependency}")

    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    service = compose_service_block(compose, "rust-actix")
    require("context: ./apps/rust-actix" in service, "rust-actix build context is incorrect")
    require("condition: service_healthy" in service, "rust-actix does not wait for PostgreSQL health")
    require('127.0.0.1:8080:8080' in service, "rust-actix host port is not loopback-only")
    require(re.search(r"(?m)^    cpus: 1(?:\.0)?\s*$", service) is not None, "rust-actix CPU limit is not 1")
    require(re.search(r"(?m)^    mem_limit: 512m\s*$", service) is not None, "rust-actix memory limit is not 512 MB")
    require("/usr/local/bin/rust-actix" in service, "rust-actix health check is missing")

    dockerfile = (RUST_APP / "Dockerfile").read_text(encoding="utf-8")
    require("FROM rust:1.98.1-bookworm" in dockerfile, "Rust builder image is not version-pinned")
    require("cargo build --release --locked" in dockerfile, "release build is missing")
    require("FROM debian:bookworm-slim" in dockerfile, "runtime image is not Debian slim")
    require("USER 65532:65532" in dockerfile, "runtime does not use the non-root user")
    require(
        'ENTRYPOINT ["/usr/local/bin/rust-actix"]' in dockerfile,
        "runtime entrypoint is incorrect",
    )

    api_source = (RUST_APP / "src" / "api.rs").read_text(encoding="utf-8")
    compact_api = re.sub(r"\s+", "", api_source)
    require("fibonacci(n-1)+fibonacci(n-2)" in compact_api, "CPU implementation is not direct recursion")
    require("derive(Serialize)" in compact_api, "native Serde response types are missing")

    database_source = (RUST_APP / "src" / "database.rs").read_text(encoding="utf-8")
    require("MAX_CONNECTIONS: u32 = 10" in database_source, "database pool maximum is not 10")
    require("WHERE id = $1" in database_source, "database query is not parameterized")

    item_source = (RUST_APP / "src" / "item.rs").read_text(encoding="utf-8")
    require(".bind(id)" in item_source, "database ID is not bound as a query parameter")

    main_source = (RUST_APP / "src" / "main.rs").read_text(encoding="utf-8")
    require("const WORKERS: usize = 1" in main_source, "worker count is not fixed at one")
    require(".workers(WORKERS)" in main_source, "Actix worker count is not applied")

    makefile = MAKEFILE.read_text(encoding="utf-8")
    require(
        re.search(r"(?m)^test-rust-actix\s*:", makefile) is not None,
        "Makefile target is missing: test-rust-actix",
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
    container_id = run(["docker", "compose", "ps", "--quiet", "rust-actix"]).stdout.strip()
    require(bool(container_id), "rust-actix container is not running")

    state = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Health.Status}}|{{.RestartCount}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}|{{.Config.User}}",
            container_id,
        ]
    ).stdout.strip()
    require(
        state == "healthy|0|1000000000|536870912|65532:65532",
        f"unexpected rust-actix container configuration: {state!r}",
    )


def check_dynamic_contract() -> None:
    run(["cargo", "fmt", "--check"], cwd=RUST_APP)
    run(["cargo", "test", "--locked"], cwd=RUST_APP, timeout=600)
    run(
        [
            "cargo",
            "clippy",
            "--locked",
            "--all-targets",
            "--all-features",
            "--",
            "-D",
            "warnings",
        ],
        cwd=RUST_APP,
        timeout=600,
    )
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
                "240",
                "rust-actix",
            ],
            timeout=1200,
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
        help="validate repository files without running Rust or Docker",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except CheckFailure as exc:
        print(f"Rust / Actix Web service check failed: {exc}", file=sys.stderr)
        return 1

    mode = "static contract" if args.static else "Rust / Actix Web service"
    print(f"{mode} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
