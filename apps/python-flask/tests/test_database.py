"""Focused synchronous PostgreSQL pool tests."""

from unittest.mock import MagicMock

import pytest

from benchmark_api import database

ENV = {
    "DATABASE_HOST": "postgres",
    "DATABASE_PORT": "5432",
    "DATABASE_NAME": "benchmark",
    "DATABASE_USER": "benchmark",
    "DATABASE_PASSWORD": "benchmark",
}


def test_pool_settings_use_shared_limits():
    dsn, options = database.pool_settings(ENV)
    assert "host=postgres" in dsn
    assert "port=5432" in dsn
    assert "dbname=benchmark" in dsn
    assert options == {"min_size": 1, "max_size": 10, "timeout": 5, "open": False}


@pytest.mark.parametrize("key", ENV)
def test_pool_settings_require_every_database_value(key):
    env = dict(ENV)
    env[key] = ""
    with pytest.raises(ValueError):
        database.pool_settings(env)


@pytest.mark.parametrize("port", ["", "0", "65536", "abc", "1.0"])
def test_pool_settings_reject_invalid_port(port):
    env = dict(ENV)
    env["DATABASE_PORT"] = port
    with pytest.raises(ValueError):
        database.pool_settings(env)


def test_fetch_item_uses_bound_parameter():
    cursor = MagicMock()
    cursor.fetchone.return_value = (42, "Item 42", 4200)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    pool = MagicMock()
    pool.connection.return_value.__enter__.return_value = connection
    assert database.fetch_item(pool, 42) == (42, "Item 42", 4200)
    cursor.execute.assert_called_once_with(database.ITEM_QUERY, (42,))
    pool.connection.assert_called_once_with(timeout=5)


def test_close_pool_is_bounded_and_sanitized():
    pool = MagicMock()
    database.close_pool(pool)
    pool.close.assert_called_once_with(timeout=5)
    pool.close.side_effect = RuntimeError("secret")
    with pytest.raises(RuntimeError, match="database shutdown failed"):
        database.close_pool(pool)
