#!/usr/bin/env python3
"""Document the completed Rust / Actix Web implementation for Issue #4."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def insert_before(path: str, marker: str, addition: str, sentinel: str) -> None:
    target = ROOT / path
    content = target.read_text(encoding="utf-8")
    if sentinel in content:
        return
    if marker not in content:
        raise RuntimeError(f"marker not found in {path}: {marker!r}")
    target.write_text(content.replace(marker, addition.strip() + "\n\n" + marker, 1), encoding="utf-8")


insert_before(
    "README.md",
    "## Planned usage",
    r'''
## Rust / Actix Web implementation

The Rust implementation lives in `apps/rust-actix/` and uses Rust 1.98.1, Actix Web 4.15.0, and SQLx 0.9.0. It runs exactly one Actix worker with a PostgreSQL pool capped at 10 connections. Docker Compose limits the API container to 1 CPU and 512 MB, runs it as non-root user `65532:65532`, and publishes port `8080` only on the loopback interface.

```bash
docker compose up --detach --build --wait rust-actix
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
```

Run the complete Rust formatting, unit-test, Clippy, container, API-contract, resource-limit, and cleanup checks with:

```bash
make test-rust-actix
```
''',
    "## Rust / Actix Web implementation",
)

insert_before(
    "README.ja.md",
    "## 実行方法の目標",
    r'''
## Rust / Actix Web実装

Rust実装は`apps/rust-actix/`にあり、Rust 1.98.1、Actix Web 4.15.0、SQLx 0.9.0を使用します。Actix workerは厳密に1つ、PostgreSQLのpool上限は10接続です。Docker ComposeではAPIコンテナを1 CPU・512 MBに制限し、非rootユーザー`65532:65532`で実行します。ポート`8080`はloopback interfaceだけに公開します。

```bash
docker compose up --detach --build --wait rust-actix
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/json
curl http://127.0.0.1:8080/db/42
curl http://127.0.0.1:8080/cpu
make down
```

Rustのformat、unit test、Clippy、コンテナ起動、API仕様、リソース制限、クリーンアップをまとめて確認するには、次を実行します。

```bash
make test-rust-actix
```
''',
    "## Rust / Actix Web実装",
)

insert_before(
    "ARCHITECTURE.md",
    "### PostgreSQL",
    r'''
#### Rust / Actix Web

The Rust implementation lives in `apps/rust-actix/`. It uses Rust 1.98.1, Actix Web 4.15.0, and SQLx 0.9.0. `src/main.rs` owns process startup and fixes the Actix worker count at one, `src/api.rs` owns the HTTP contract, `src/database.rs` owns PostgreSQL connection configuration, and `src/item.rs` owns the parameterized item lookup abstraction.

The process listens on internal port `8080`, reads the shared `DATABASE_*` settings, and caps the SQLx pool at 10 connections. `/db/{id}` validates the identifier before binding it to the query, while `/cpu` performs direct, uncached recursion for Fibonacci(30) on every request.

The production image is a release multi-stage build and runs as numeric non-root user `65532:65532`. Compose limits the container to 1 CPU and 512 MB, waits for PostgreSQL to become healthy, and publishes API port `8080` only on `127.0.0.1`. The image health check invokes the same binary in `healthcheck` mode.
''',
    "#### Rust / Actix Web",
)

insert_before(
    "docs/METHODOLOGY.md",
    "## Tests",
    r'''
## Implemented stack baselines

The current Go baseline uses Go 1.27.1, Gin 1.12.0, and pgx/v5 5.10.0. The current Rust baseline uses Rust 1.98.1, Actix Web 4.15.0, and SQLx 0.9.0. Both implementations use one server process or worker, the shared pool maximum of 10 connections, and the same Compose resource limits. Published result files record these versions so later dependency updates remain visible.
''',
    "## Implemented stack baselines",
)

insert_before(
    "CONTRIBUTING.md",
    "The following project-wide commands are added by later v0.1 issues:",
    r'''
The complete Rust / Actix Web validation is:

```bash
make test-rust-actix
```

For a faster source-only check while working under `apps/rust-actix/`, run:

```bash
cargo fmt --check
cargo test --locked
cargo clippy --locked --all-targets --all-features -- -D warnings
```

`make test-rust-actix` additionally builds the release image, starts PostgreSQL and Rust / Actix Web through Compose, verifies every documented endpoint, checks the worker, pool, and container constraints, and removes all project containers afterward.
''',
    "The complete Rust / Actix Web validation is:",
)
