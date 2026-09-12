# Python / Flask implementation

`apps/python-flask/` is the synchronous Python comparison stack. It is intentionally a complete-stack comparison with Python / FastAPI, not an isolated Flask-versus-FastAPI router benchmark.

## Approved production profile

- CPython 3.14.7, matching the FastAPI baseline.
- Flask 3.1.3.
- Waitress 3.0.2 as the production WSGI server.
- One server OS process and exactly one Waitress worker thread.
- psycopg 3.3.5 with the binary implementation package pinned to the same version.
- psycopg-pool 3.3.1 with `min_size=1`, `max_size=10`.
- The same PostgreSQL fixture, parameterized lookup SQL, 1 CPU / 512 MiB container budget, loopback-only host publication, dropped capabilities, no-new-privileges policy, and non-root runtime used by the other implementations.

Flask's development server, Gunicorn master/worker processes, gevent/event-loop monkey patching, extra middleware, response caches, and precomputed CPU results are not used.

## HTTP behavior

The implementation provides the unchanged shared contract:

- `GET /health`
- `GET /json`
- `GET /db/:id`
- `GET /cpu`

`/db/:id` validates the complete signed PostgreSQL BIGINT range before acquiring a connection. SQL values are bound parameters. Driver exceptions are converted to the shared sanitized `500` response. `/cpu` performs direct recursive Fibonacci(30) for each request.

## Startup and shutdown

PostgreSQL pool creation and a real `SELECT 1` readiness query complete before Waitress begins accepting HTTP traffic. SIGINT and SIGTERM close the listener, Waitress drains/shuts down its single task-dispatcher thread with a bounded timeout, and the PostgreSQL pool is then closed.

The production image starts directly with:

```text
python -m benchmark_api.server
```

There is no supervisor or second worker process.

## Verification

Run the implementation-specific gates with:

```bash
make test-python-flask
make test-contract CONTRACT_IMPL=python-flask
```

The gates cover unit behavior, dependency/hash locks, real PostgreSQL and Docker acceptance, exact signed BIGINT JSON numbers, database updates and failures, startup failure, resource/process isolation, SIGTERM shutdown, and cleanup.

## Publication boundary

Python / Flask is registered and CI-covered, but Issue #32 does not activate a new official benchmark cohort. `active_cohort` remains the frozen `four-stack-v1`; expanded-cohort activation and new official measurements are separate work.
