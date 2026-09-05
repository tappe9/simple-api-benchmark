# Contributing

Thank you for helping keep Simple API Benchmark useful and easy to understand.

## Project rule

A contribution should make at least one of these things better without making the project harder to understand:

- the comparison is fairer;
- the result is easier to read;
- the benchmark is easier to reproduce;
- an implementation follows the shared API contract more closely.

## Before opening a pull request

Open or comment on an issue first when proposing:

- a new language or framework;
- a new benchmark endpoint;
- a change to CPU, memory, duration, or connection settings;
- a change that would make old and new results difficult to compare.

Small documentation corrections and clear bug fixes may go directly to a pull request.

## Development language

Use English for source code, identifiers, commit messages, issues, and pull requests. User-facing documentation may provide both English and Japanese versions.

## Local commands

The shared PostgreSQL environment is available now:

```bash
make db-up
make db-check
make db-reset
make test-db
make down
```

Run `make test-db` after changing `docker-compose.yml`, `database/init.sql`, the database-related Makefile targets, or their acceptance checks. It performs startup, fixture validation, reset validation, and cleanup. Run `make down` after interrupted manual work.

The complete Go / Gin validation is:

```bash
make test-go-gin
```

For a faster source-only check while working under `apps/go-gin/`, run:

```bash
test -z "$(gofmt -l .)"
go test ./...
go vet ./...
```

`make test-go-gin` additionally builds the production image, starts PostgreSQL and Go / Gin through Compose, verifies every documented endpoint, checks the pool and container constraints, and removes all project containers afterward.

The complete Rust / Actix Web validation requires Rustup, Python 3, Docker Compose v2, and Make:

```bash
make test-rust-actix
```

For focused source checks without Docker:

```bash
cd apps/rust-actix
rustup toolchain install 1.98.1 --profile minimal --component rustfmt,clippy
cargo fmt --check
cargo test --locked
cargo clippy --locked --all-targets --all-features -- -D warnings
```

The toolchain file selects Rust 1.98.1. Do not regenerate `Cargo.lock`, format files, or apply automatic fixes as part of validation: verify the committed tree. The Docker builder uses a published 1.98.0 image pinned by digest and explicitly installs compiler 1.98.1; the runtime base is independently digest-pinned. Dependency and base-image changes must be intentional and validated with all available DB/API acceptance targets.

The Rust acceptance target also checks native JSON types, real database updates, signed BIGINT boundaries, sanitized query errors, a single non-root server, resource and network settings, startup failure, SIGTERM exit, and connection/container/network cleanup. It does not run a benchmark or replace the future common contract suite.

The complete Node / Fastify validation requires Node.js 24.20.0 (also recorded in `apps/node-fastify/.node-version`), npm, Python 3, Docker Compose v2, and Make:

```bash
make test-node-fastify
```

For focused tests without Docker:

```bash
cd apps/node-fastify
npm ci
npm test
npm run lint
```

Tests use the standard Node runner and Fastify's `inject()` API. `lint` is Node syntax validation, with no additional lint dependencies. The Docker acceptance check also validates actual SQL reads and updates, error responses, exact BIGINT serialization, image dependencies, a single non-root Node process, resource limits, SIGTERM shutdown, pool closure, and container/network cleanup. API implementations share host port `8080`; run them one at a time and use `make down` between manual sessions.

Run the available DB and API acceptance targets after modifying shared Compose configuration. To update the Node baseline, intentionally change the exact runtime/dependency versions, regenerate and review `package-lock.json`, verify the official image digest, and update the matching documentation and acceptance expectations. The production image installs only runtime dependencies and starts Node directly.

The complete Python / FastAPI validation requires Python 3.14.7 on a POSIX host, Docker Compose v2, and Make:

```bash
make test-python-fastapi PYTHON=python3.14
```

It creates and removes a temporary virtual environment, installs `requirements-dev.lock` with hash verification and binary wheels only, runs `pip check`, Ruff, compilation checks, and pytest, then builds and tests the production Docker service. Acceptance checks cover real SQL reads and updates, signed BIGINT boundaries, sanitized failures, startup readiness, image dependencies, one non-root Uvicorn worker, resource limits, SIGTERM pool cleanup, and removal of project containers and networks. No benchmark is run.

For focused Python tests without Docker:

```bash
cd apps/python-fastapi
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
python -m pip check
python -m ruff check .
python -m pytest -q
```

The exact Python patch version is also recorded in `.python-version`. Tests use pytest, AnyIO's asyncio backend, and HTTPX2's ASGI transport, with explicit lifespan management and warnings treated as errors. They do not need a database. Production images install only `requirements.lock`; development dependencies and tests are excluded.

When updating the Python baseline, review official releases and wheel availability for CPython 3.14, change the `.in` files and exact Python version intentionally, resolve the full runtime and development graphs in a clean environment, and record published wheel SHA256 hashes in both lock files. Review transitive changes, verify the official Docker index digest, and update the matching acceptance expectations and documentation. Never install from an unlocked `.in` file for validation or production. Rerun all DB/API acceptance targets after shared Compose changes.

The following project-wide commands are added by later v0.1 issues:

```bash
make test
make test-contract
make benchmark
```

A pull request must pass the available checks for the area it changes.

## Adding or updating an implementation

Each backend belongs under:

```text
apps/<language-framework>/
```

It must:

1. listen on port `8080`;
2. implement all endpoints in `docs/API-CONTRACT.md`;
3. use the shared PostgreSQL container and fixture;
4. respect the common CPU and memory limits;
5. use a production or release build;
6. pin direct dependencies with the ecosystem's normal lock file;
7. pass contract tests before performance measurements;
8. document non-obvious runtime or worker settings.

The following are not allowed:

- returning prebuilt JSON strings for benchmark responses;
- memoizing or precomputing Fibonacci(30);
- returning a fixed database result without executing SQL;
- skipping input parsing required by the API contract;
- using benchmark-only caches;
- changing the common resource limits for one implementation.

## Pull request checklist

- The change stays within the issue's scope.
- Documentation matches behavior.
- Direct dependencies and container base images are intentionally selected.
- New behavior has an automated test where practical.
- Local or CI checks pass.
- Benchmark numbers are not manually edited into README.
- The pull request explains any limitation or trade-off.

## Benchmark result changes

Do not commit performance claims produced on unrelated machines as official project results. Official README and GitHub Pages results are generated by the repository's benchmark workflow.

Local result files may be attached to an issue or pull request for investigation.

## Security

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
