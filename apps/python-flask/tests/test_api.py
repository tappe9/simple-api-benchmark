"""Focused Flask HTTP contract tests without PostgreSQL."""

from unittest.mock import Mock

import pytest

from benchmark_api import app as api
from benchmark_api import database


@pytest.fixture
def pool():
    return object()


@pytest.fixture
def client(monkeypatch, pool):
    monkeypatch.setattr(database, "fetch_item", Mock(return_value=(42, "Item 42", 4200)))
    return api.create_app(pool).test_client()


def assert_json(response, status, expected):
    assert response.status_code == status
    assert response.content_type == "application/json"
    payload = response.get_json()
    assert payload == expected
    for key, value in expected.items():
        assert type(payload[key]) is type(value)


def test_native_json_responses(client):
    assert_json(client.get("/health"), 200, {"status": "ok"})
    assert_json(client.get("/json"), 200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})
    assert_json(client.get("/cpu"), 200, {"input": 30, "result": 832040})


@pytest.mark.parametrize("value", [
    "invalid", "42junk", "1.0", "1e2", "0x2a", "1_000", " 42", "42 ",
    "４２", "9223372036854775808", "-9223372036854775809", "9" * 5000,
])
def test_invalid_id_is_400_without_query(client, monkeypatch, pool, value):
    fetch = Mock()
    monkeypatch.setattr(database, "fetch_item", fetch)
    assert_json(client.get(f"/db/{value}"), 400, {"error": "invalid id"})
    fetch.assert_not_called()


@pytest.mark.parametrize("value, expected", [
    ("42", 42), ("+42", 42), ("00042", 42), ("-0", 0),
    ("9007199254740993", 9007199254740993),
    ("9223372036854775807", 9223372036854775807),
    ("-9223372036854775808", -9223372036854775808),
])
def test_signed_bigint_is_exact_json_number(client, monkeypatch, pool, value, expected):
    fetch = Mock(return_value=(expected, "Boundary", 1))
    monkeypatch.setattr(database, "fetch_item", fetch)
    assert_json(client.get(f"/db/{value}"), 200, {"id": expected, "name": "Boundary", "price": 1})
    fetch.assert_called_once_with(pool, expected)


def test_missing_and_database_failure_are_sanitized(client, monkeypatch):
    monkeypatch.setattr(database, "fetch_item", Mock(return_value=None))
    assert_json(client.get("/db/999"), 404, {"error": "not found"})
    monkeypatch.setattr(database, "fetch_item", Mock(side_effect=RuntimeError("password=secret")))
    assert_json(client.get("/db/42"), 500, {"error": "internal server error"})


def test_cpu_calculates_every_request(client, monkeypatch):
    calls = []
    def calculate(n):
        calls.append(n)
        return len(calls)
    monkeypatch.setattr(api, "fibonacci", calculate)
    assert_json(client.get("/cpu"), 200, {"input": 30, "result": 1})
    assert_json(client.get("/cpu"), 200, {"input": 30, "result": 2})
    assert calls == [30, 30]
