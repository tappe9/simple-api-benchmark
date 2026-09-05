FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS dependencies

WORKDIR /build
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock \
    && /opt/venv/bin/python -m pip check

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY benchmark_api ./benchmark_api
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["benchmark_api.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--loop", "asyncio", "--http", "h11", "--no-access-log", "--timeout-graceful-shutdown", "5"]
