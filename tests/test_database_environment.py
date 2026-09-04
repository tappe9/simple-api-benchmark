#!/usr/bin/env python3
"""Acceptance checks for the shared PostgreSQL benchmark environment."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"
INIT_SQL = ROOT / "database" / "init.sql"
MAKEFILE = ROOT / "Makefile"

POSTGRES_IMAGE = (
    "postgres:18.6-bookworm@"
    "sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
)
EXPECTED_ROW = "42|Item 42|4200"
EXPECTED_COUNT = "1"


class CheckFailure(RuntimeError):
    """Raised when an environment contract check fails."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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


def run(
    command: Sequence[str],
    *,
    timeout: int = 180,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
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
    for path in (COMPOSE_FILE, INIT_SQL, MAKEFILE):
        require(path.is_file(), f"required file is missing: {path.relative_to(ROOT)}")

    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    require(not re.search(r"(?m)^version\s*:", compose), "obsolete Compose version key found")
    require("postgres:" in compose, "postgres service is missing")
    require(POSTGRES_IMAGE in compose, "PostgreSQL image is not pinned to the expected tag and digest")
    require("pg_isready" in compose, "PostgreSQL health check is missing")
    require("/var/lib/postgresql" in compose, "PostgreSQL data directory is not backed by tmpfs")
    require("tmpfs:" in compose, "tmpfs configuration is missing")
    postgres = compose_service_block(compose, "postgres")
    require(
        re.search(r"(?m)^    ports\s*:", postgres) is None,
        "PostgreSQL must not publish a host port",
    )
    require(re.search(r"(?m)^\s+benchmark:\s*$", compose) is not None, "benchmark network is missing")

    expected_environment = {
        "DATABASE_HOST: postgres",
        'DATABASE_PORT: "5432"',
        "DATABASE_NAME: benchmark",
        "DATABASE_USER: benchmark",
        "DATABASE_PASSWORD: benchmark",
        "POSTGRES_DB: benchmark",
        "POSTGRES_USER: benchmark",
        "POSTGRES_PASSWORD: benchmark",
    }
    for entry in expected_environment:
        require(entry in compose, f"Compose connection setting is missing: {entry}")

    sql = normalized_sql(INIT_SQL.read_text(encoding="utf-8"))
    require(
        "CREATE TABLE items ( id BIGINT PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL );"
        in sql,
        "items table definition does not match the API contract",
    )
    require(
        "INSERT INTO items (id, name, price) VALUES (42, 'Item 42', 4200);" in sql,
        "fixture row does not match the API contract",
    )

    makefile = MAKEFILE.read_text(encoding="utf-8")
    for target in ("db-up", "db-check", "db-reset", "test-db", "down"):
        require(
            re.search(rf"(?m)^{re.escape(target)}\s*:", makefile) is not None,
            f"Makefile target is missing: {target}",
        )


def query(sql: str) -> str:
    completed = run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "--username",
            "benchmark",
            "--dbname",
            "benchmark",
            "--set",
            "ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--field-separator",
            "|",
            "--command",
            sql,
        ]
    )
    return completed.stdout.strip()


def check_fixture() -> None:
    row = query("SELECT id, name, price FROM items WHERE id = 42;")
    require(row == EXPECTED_ROW, f"unexpected fixture row: {row!r}")

    count = query("SELECT COUNT(*) FROM items;")
    require(count == EXPECTED_COUNT, f"unexpected item count: {count!r}")


def check_dynamic_contract() -> None:
    run(["docker", "compose", "config"])

    primary_error: BaseException | None = None
    try:
        run(["make", "db-up"], timeout=300)
        run(["make", "db-up"], timeout=300)

        container_id = run(
            ["docker", "compose", "ps", "--quiet", "postgres"]
        ).stdout.strip()
        require(bool(container_id), "PostgreSQL container is not running")

        health = run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_id,
            ]
        ).stdout.strip()
        require(health == "healthy", f"PostgreSQL health status is {health!r}")
        check_fixture()

        query("INSERT INTO items (id, name, price) VALUES (99, 'Temporary item', 1);")
        require(query("SELECT COUNT(*) FROM items;") == "2", "temporary mutation was not applied")

        run(["make", "db-reset"], timeout=300)
        check_fixture()
        require(
            query("SELECT COUNT(*) FROM items WHERE id = 99;") == "0",
            "db-reset retained data from the previous environment",
        )

        run(["make", "db-reset"], timeout=300)
        check_fixture()
    except BaseException as exc:  # Preserve the first failure while still checking cleanup.
        primary_error = exc
    finally:
        cleanup = run(["make", "down"], check=False)
        repeated_cleanup = run(["make", "down"], check=False)
        remaining = run(
            ["docker", "compose", "ps", "-a", "--quiet"],
            check=False,
        )
        cleanup_error: CheckFailure | None = None
        if cleanup.returncode != 0:
            cleanup_error = CheckFailure(
                f"make down exited with status {cleanup.returncode}"
            )
        elif repeated_cleanup.returncode != 0:
            cleanup_error = CheckFailure(
                "repeated make down exited with status "
                f"{repeated_cleanup.returncode}"
            )
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
        help="validate repository files without starting Docker",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_static_contract()
        if not args.static:
            check_dynamic_contract()
    except CheckFailure as exc:
        print(f"database environment check failed: {exc}", file=sys.stderr)
        return 1

    mode = "static contract" if args.static else "database environment"
    print(f"{mode} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
