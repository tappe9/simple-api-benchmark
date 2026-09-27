# Python / Flask implementation

`apps/python-flask/` is the synchronous Python comparison stack. It is intentionally a complete-stack comparison with Python / FastAPI, not an isolated Flask-versus-FastAPI router benchmark.

## Approved production profile

- CPython 3.14.7, matching the FastAPI baseline.
- Flask 3.1.3.
- Gunicorn 26.0.0 as the production WSGI server, using one `gthread` request worker with one thread.
- One Gunicorn arbiter plus exactly one request-processing worker and one request thread.
- psycopg 3.3.5 with the binary implementation package pinned to the same version.
- psycopg-pool 3.3.1 with `min_size=1`, `max_size=10`.
- The same PostgreSQL fixture, parameterized lookup SQL, 1 CPU / 512 MiB container budget, loopback-only host publication, dropped capabilities, no-new-privileges policy, and non-root runtime used by the other implementations.

Flask's development server, gevent/event-loop monkey patching, extra middleware, response caches, and precomputed CPU results are not used.

## HTTP behavior

The implementation provides the unchanged shared contract:

- `GET /health`
- `GET /json`
- `GET /db/:id`
- `GET /cpu`

`/db/:id` validates the complete signed PostgreSQL BIGINT range before acquiring a connection. SQL values are bound parameters. Driver exceptions are converted to the shared sanitized `500` response. `/cpu` performs direct recursive Fibonacci(30) for each request.

## Startup and shutdown

Each Gunicorn worker creates its own PostgreSQL pool and proves readiness with a real `SELECT 1` before its Flask application is returned. Gunicorn handles SIGTERM and bounded graceful worker shutdown; worker-local pool cleanup is registered with Python `atexit`.

The production image starts directly with:

```text
python -m gunicorn.app.wsgiapp --workers 1 --worker-class gthread --threads 1 … 'benchmark_api.server:create_server_app()'
```

Gunicorn uses one arbiter process and one request-processing worker; it does not add request workers beyond the benchmark profile's single worker.

## Verification

Run the implementation-specific gates with:

```bash
make test-python-flask
make test-contract CONTRACT_IMPL=python-flask
```

The gates cover unit behavior, dependency/hash locks, real PostgreSQL and Docker acceptance, exact signed BIGINT JSON numbers, database updates and failures, startup failure, resource/process isolation, SIGTERM shutdown, and cleanup.

## Publication boundary

See the shared [registration, CI and cohort status](IMPLEMENTATIONS.md#registered-and-measured-implementations)
for Flask's place in the comparison. The production profile above describes
current main, not the server used in older measurements. The
[published-result boundary](IMPLEMENTATIONS.md#published-results-and-runtime-changes)
distinguishes the recorded Waitress result from the current Gunicorn runtime;
changing the runtime does not update or relabel published measurements.
