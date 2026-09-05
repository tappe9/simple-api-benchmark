"""Focused HTTP and application lifecycle tests; no PostgreSQL required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from benchmark_api import app as api
from benchmark_api import database

QUERY = "SELECT id, name, price FROM items WHERE id = $1"


@pytest.fixture
def pool():
    return SimpleNamespace(fetchrow=AsyncMock(return_value={"id": 42, "name": "Item 42", "price": 4200}))


@pytest.fixture
def client(monkeypatch, pool):
    monkeypatch.setattr(database, "open_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(database, "close_pool", AsyncMock())
    with TestClient(api.create_app()) as client:
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
def test_native_json_responses(client, pool, path, expected):
    assert_json(client.get(path), 200, expected)
    pool.fetchrow.assert_not_awaited()


def test_database_row_is_queried_on_every_request(client, pool):
    assert_json(client.get("/db/42"), 200, {"id": 42, "name": "Item 42", "price": 4200})
    pool.fetchrow.assert_awaited_once_with(QUERY, 42)
    pool.fetchrow.return_value = {"id": 42, "name": "Changed", "price": 7}
    assert_json(client.get("/db/42"), 200, {"id": 42, "name": "Changed", "price": 7})
    assert pool.fetchrow.await_count == 2


@pytest.mark.parametrize("value", [
    "invalid", "42junk", "1.0", "1e2", "0x2a", "1_000", "%2042", "42%20",
    "%EF%BC%94%EF%BC%92", "%2B", "--1", "42%27%20OR%201%3D1",
    "9223372036854775808", "-9223372036854775809", "9" * 5000,
])
def test_invalid_id_is_400_without_query(client, pool, value):
    assert_json(client.get(f"/db/{value}"), 400, {"error": "invalid id"})
    pool.fetchrow.assert_not_awaited()


@pytest.mark.parametrize("value, expected", [
    ("+42", 42), ("00042", 42), ("-0", 0),
    ("9007199254740993", 9007199254740993),
    ("9223372036854775807", 9223372036854775807),
    ("-9223372036854775808", -9223372036854775808),
])
def test_signed_bigint_uses_exact_numeric_json(client, pool, value, expected):
    pool.fetchrow.return_value = {"id": expected, "name": "Boundary", "price": 1}
    assert_json(client.get(f"/db/{value}"), 200, {"id": expected, "name": "Boundary", "price": 1})
    pool.fetchrow.assert_awaited_once_with(QUERY, expected)


def test_missing_row_is_404(client, pool):
    pool.fetchrow.return_value = None
    assert_json(client.get("/db/999"), 404, {"error": "not found"})
    pool.fetchrow.assert_awaited_once_with(QUERY, 999)


@pytest.mark.parametrize("error", [RuntimeError("password=secret SELECT items"), OSError("private-host"), TimeoutError()])
def test_database_error_is_sanitized(client, pool, error):
    pool.fetchrow.side_effect = error
    assert_json(client.get("/db/42"), 500, {"error": "internal server error"})


def test_cpu_invokes_calculation_for_each_request(client, monkeypatch):
    calls = []

    def calculate(n):
        calls.append(n)
        return len(calls)

    monkeypatch.setattr(api, "fibonacci", calculate)
    assert_json(client.get("/cpu"), 200, {"input": 30, "result": 1})
    assert_json(client.get("/cpu"), 200, {"input": 30, "result": 2})
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


def test_lifespan_opens_before_serving_and_closes_pool(monkeypatch, pool):
    opened = AsyncMock(return_value=pool)
    closed = AsyncMock()
    monkeypatch.setattr(database, "open_pool", opened)
    monkeypatch.setattr(database, "close_pool", closed)
    with TestClient(api.create_app()) as client:
        opened.assert_awaited_once_with()
        closed.assert_not_awaited()
        assert_json(client.get("/health"), 200, {"status": "ok"})
    closed.assert_awaited_once_with(pool)


def test_startup_failure_prevents_serving(monkeypatch):
    monkeypatch.setattr(database, "open_pool", AsyncMock(side_effect=RuntimeError("database startup failed")))
    with pytest.raises(RuntimeError, match="database startup failed"), TestClient(api.create_app()):
        pytest.fail("application accepted requests without a database")
