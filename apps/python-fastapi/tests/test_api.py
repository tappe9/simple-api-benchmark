"""Focused HTTP and application lifecycle tests; no PostgreSQL required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx2 import ASGITransport, AsyncClient

from benchmark_api import app as api
from benchmark_api import database

QUERY = "SELECT id, name, price FROM items WHERE id = $1"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def pool():
    return SimpleNamespace(fetchrow=AsyncMock(return_value={"id": 42, "name": "Item 42", "price": 4200}))


@pytest.fixture
async def client(monkeypatch, pool):
    monkeypatch.setattr(database, "open_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(database, "close_pool", AsyncMock())
    app = api.create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


def assert_json(response, status, expected):
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload == expected
    for key, value in expected.items():
        assert type(payload[key]) is type(value)
        if isinstance(value, list):
            assert all(type(item) is int for item in payload[key])


@pytest.mark.parametrize("path, expected", [
    ("/health", {"status": "ok"}),
    ("/json", {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]}),
    ("/cpu", {"input": 30, "result": 832040}),
])
async def test_native_json_responses(client, pool, path, expected):
    assert_json(await client.get(path), 200, expected)
    pool.fetchrow.assert_not_awaited()


async def test_database_row_is_queried_on_every_request(client, pool):
    assert_json(await client.get("/db/42"), 200, {"id": 42, "name": "Item 42", "price": 4200})
    pool.fetchrow.assert_awaited_once_with(QUERY, 42)
    pool.fetchrow.return_value = {"id": 42, "name": "Changed", "price": 7}
    assert_json(await client.get("/db/42"), 200, {"id": 42, "name": "Changed", "price": 7})
    assert pool.fetchrow.await_count == 2


@pytest.mark.parametrize("value", [
    "invalid", "42junk", "1.0", "1e2", "0x2a", "1_000", "%2042", "42%20",
    "%EF%BC%94%EF%BC%92", "%2B", "--1", "42%27%20OR%201%3D1",
    "9223372036854775808", "-9223372036854775809", "9" * 5000,
])
async def test_invalid_id_is_400_without_query(client, pool, value):
    assert_json(await client.get(f"/db/{value}"), 400, {"error": "invalid id"})
    pool.fetchrow.assert_not_awaited()


@pytest.mark.parametrize("value, expected", [
    ("+42", 42), ("00042", 42), ("-0", 0),
    ("9007199254740993", 9007199254740993),
    ("9223372036854775807", 9223372036854775807),
    ("-9223372036854775808", -9223372036854775808),
])
async def test_signed_bigint_uses_exact_numeric_json(client, pool, value, expected):
    pool.fetchrow.return_value = {"id": expected, "name": "Boundary", "price": 1}
    assert_json(await client.get(f"/db/{value}"), 200, {"id": expected, "name": "Boundary", "price": 1})
    pool.fetchrow.assert_awaited_once_with(QUERY, expected)


async def test_missing_row_is_404(client, pool):
    pool.fetchrow.return_value = None
    assert_json(await client.get("/db/999"), 404, {"error": "not found"})
    pool.fetchrow.assert_awaited_once_with(QUERY, 999)


@pytest.mark.parametrize("error", [RuntimeError("password=secret SELECT items"), OSError("private-host"), TimeoutError()])
async def test_database_error_is_sanitized(client, pool, error):
    pool.fetchrow.side_effect = error
    assert_json(await client.get("/db/42"), 500, {"error": "internal server error"})


async def test_cpu_invokes_calculation_for_each_request(client, monkeypatch):
    calls = []

    def calculate(n):
        calls.append(n)
        return len(calls)

    monkeypatch.setattr(api, "fibonacci", calculate)
    assert_json(await client.get("/cpu"), 200, {"input": 30, "result": 1})
    assert_json(await client.get("/cpu"), 200, {"input": 30, "result": 2})
    assert calls == [30, 30]


def test_fibonacci_is_direct_recursion(monkeypatch):
    original = api.fibonacci
    calls = []

    def observe(n):
        calls.append(n)
        return original(n)

    monkeypatch.setattr(api, "fibonacci", observe)
    assert observe(5) == 5
    assert len(calls) == 15
    assert calls.count(0) == 3
    assert calls.count(1) == 5


async def test_lifespan_opens_before_serving_and_closes_pool(monkeypatch, pool):
    opened = AsyncMock(return_value=pool)
    closed = AsyncMock()
    monkeypatch.setattr(database, "open_pool", opened)
    monkeypatch.setattr(database, "close_pool", closed)
    app = api.create_app()
    async with app.router.lifespan_context(app):
        opened.assert_awaited_once_with()
        closed.assert_not_awaited()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert_json(await client.get("/health"), 200, {"status": "ok"})
    closed.assert_awaited_once_with(pool)


async def test_startup_failure_prevents_serving(monkeypatch):
    monkeypatch.setattr(database, "open_pool", AsyncMock(side_effect=RuntimeError("database startup failed")))
    app = api.create_app()
    with pytest.raises(RuntimeError, match="database startup failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("application accepted requests without a database")
