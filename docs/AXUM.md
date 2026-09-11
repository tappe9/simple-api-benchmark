# Rust / Axum implementation and diagnostic

## Status and comparison boundary

`rust-axum` is an independent implementation under `apps/rust-axum/`, registered
for normal CI and the unchanged shared API contract. It is **not** a member of the
active `four-stack-v1` cohort. Adding it does not change `results/latest.json`,
historical results, numeric README blocks, or the existing Actix application.
Activating a complete expanded cohort requires a separate reviewed change; see
[implementation registration](IMPLEMENTATIONS.md).

Axum uses its own router, Hyper HTTP server, Tower service integration and Tokio
executor. Actix uses its Actix server/worker model. Their complete runtime and
HTTP stacks differ even with the same compiler, SQLx, serializer and resource
limits. A future comparison is not a language-only or framework-only ranking.
The short diagnostic below cannot establish an official performance ordering.

## Pinned build and runtime

| Component | Axum implementation |
| --- | --- |
| Rust compiler | 1.98.1 |
| Axum | 0.8.9 |
| Tokio | 1.53.1 |
| SQLx | 0.9.0 |
| Serde / serde_json | 1.0.228 / 1.0.145 |
| Async executor | Explicit Tokio `current_thread`, one async worker |
| Container limits | 1 CPU, 512 MiB, no restart |
| PostgreSQL pool | At most 10 connections; five-second acquire timeout |
| Runtime user | `65532:65532` |

`Cargo.toml` pins direct versions and disables unnecessary default features.
`Cargo.lock` fixes the transitive graph, including the HTTP/runtime dependencies.
The Dockerfile uses the same digest-pinned Rust 1.98.0 Bookworm builder as Actix,
explicitly installs compiler 1.98.1, and runs
`cargo +1.98.1 build --release --locked`. The independently digest-pinned Debian
Bookworm slim final image contains the release binary, not Cargo, rustc, tests or
source. The Actix source and dependency pins are not modified.

One direct server process listens on internal `0.0.0.0:8080`. Compose inherits the
shared loopback-only host port, PostgreSQL readiness dependency, local database
settings, network, dropped capabilities and `no-new-privileges` policy. The
current-thread executor runs async request work on one thread; runtime helper
threads or the separate normal Compose health probe are not additional async
workers. The application does not enable a multi-thread executor, offload CPU
work with `spawn_blocking`, or add worker processes.

`/json`, `/db/{id}` and `/cpu` use normal Serde values. IDs are parsed into signed
64-bit integers before the bound-parameter SQL query. Missing rows return 404;
invalid IDs return 400 without a database lookup; database failures return only
`{"error":"internal server error"}`. `/cpu` directly recurses for Fibonacci(30)
on every request, without memoization, precomputation or a response cache.
The shared fixture and SQL are unchanged.

Startup validates configuration and connects to PostgreSQL before accepting HTTP
requests. Configuration and connection errors omit credentials. The binary's
`healthcheck` command checks the HTTP readiness response independently of database
configuration. Both SIGINT and SIGTERM are installed before serving. Axum drains
in-flight HTTP requests before the SQLx pool is closed; a real-socket Rust test
holds a request open and proves that shutdown waits for it. Container acceptance
also verifies normal SIGTERM exit and zero remaining application DB connections.

## Validation commands

Run commands from the repository root, sequentially, with port 8080 free.
Full acceptance requires Rustup, Python 3, Make and a local Linux-container Docker
Compose v2 environment. Focused Rust checks do not require Docker or PostgreSQL:

```bash
(cd apps/rust-axum && cargo fmt --check && cargo test --locked && \
  cargo clippy --locked --all-targets --all-features -- -D warnings)

COMPOSE_PROJECT_NAME=sab-local-axum make test-rust-axum
make test-contract CONTRACT_IMPL=rust-axum
```

The acceptance target runs Rust format/tests/Clippy, builds the production image,
and checks the live HTTP/PostgreSQL service. Coverage includes JSON integer types,
updated rows rather than cached responses, BIGINT boundaries beyond JavaScript's
safe integer range, malformed IDs, sanitized database errors, startup failure,
container resources and privileges, direct server process, graceful exit, and
owned container/network cleanup. The focused Python acceptance tests also prove
that wrong response types and duplicate/missing server processes are rejected.
The shared contract still reads the same examples from `API-CONTRACT.md` and
executes two rounds of seven checks for every implementation.

## Non-publishing load diagnostic

With source changes committed, Python 3.10+, Git, curl, Make and a local Unix-socket
Docker daemon, run:

```bash
make axum-diagnostic
```

`benchmark/axum_diagnostic.py` reuses the checksum-pinned oha installer,
`DockerEnvironment`, shared contract, strict measurement parser, memory sampling
and whole-run median selection. It builds and starts **only Axum**, checks the
shared contract, then uses a fixed diagnostic profile:

- `/json`, `/db/42` and `/cpu`, in that order;
- one-second warm-up, then three two-second measurements per endpoint;
- two HTTP/1.1 connections, 15-second request timeout, unchanged resource/pool limits.

The existing `external-readiness` policy disables the owned API's recurring
container healthcheck only for load measurement. Readiness is checked from the
host before the shared contract and load; normal acceptance retains Compose
healthchecks. No official profile, cohort membership or publication workflow is
changed. A short diagnostic is not interchangeable with the official 50-connection,
three-by-30-second profile or with results from another runner.

Each invocation uses an owned random `sab-benchmark-*` project and writes below
`.cache/axum-diagnostic/<project>/`. Raw oha JSON, timestamped memory samples and
build logs support inspection. A successful `diagnostic.json` records source
commit/tree, lock hashes, Axum/compiler/dependency versions, environment and image
metadata, readiness evidence, the exact conditions and all nine measured runs.
Its mode is `axum-diagnostic`, with `official: false` and `publishable: false`;
its structure is rejected by the official report validator.

The final diagnostic is written atomically **after** all checks, measurements and
cleanup succeed. Request errors, timeouts, invalid metrics, startup failures,
handled SIGINT/SIGTERM or cleanup failures return nonzero and do not write a
partial successful diagnostic or replace published results. Output paths cannot
escape the dedicated cache or traverse symlinks. Raw failure evidence may remain
for debugging. SIGKILL or host failure cannot run cleanup; in that case inspect
the printed project name and remove only that owned project manually.

## Normal CI integration

The registry generates the normal six-implementation CI matrix. Axum's job runs
its acceptance, focused shared contract and then this diagnostic as required
steps, with read-only repository permissions. The existing `required` aggregate
rejects any failed, cancelled or skipped matrix job. The Axum job additionally
checks that tracked and untracked source files remain clean after the diagnostic.

The `axum-diagnostic-<run>-<attempt>` artifact retains the dedicated cache for seven
days and is uploaded on success or failure when available. A PR run may record
GitHub's tested merge commit as `source_commit`; use the artifact's actual source
and tree instead of assuming that SHA equals the branch head. This artifact is
never an input to official publication or Pages deployment. The temporary
`axum-development.yml` workflow is removed; no diagnostic-only workflow or write
permission is added. `make test` runs the diagnostic sequentially after the
unchanged active-cohort smoke benchmark.
