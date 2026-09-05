"""Focused PostgreSQL configuration, readiness, and cleanup tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest

from benchmark_api import database

ENV = {
    "DATABASE_HOST": "postgres", "DATABASE_PORT": "5432", "DATABASE_NAME": "benchmark",
    "DATABASE_USER": "benchmark", "DATABASE_PASSWORD": "secret:@/password",
}


@pytest.fixture
def environment(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)


def fake_pool():
    return SimpleNamespace(fetchval=AsyncMock(return_value=1), close=AsyncMock(), terminate=Mock())


def test_pool_settings_use_all_shared_values_and_cap_ten():
    options = database.pool_options(ENV)
    assert options == {
        "host": "postgres", "port": 5432, "database": "benchmark", "user": "benchmark",
        "password": "secret:@/password", "min_size": 1, "max_size": 10,
        "timeout": 5, "command_timeout": 5, "ssl": False,
    }


@pytest.mark.parametrize("key", ENV)
@pytest.mark.parametrize("value", [None, ""])
def test_every_database_setting_is_required(key, value):
    env = dict(ENV)
    if value is None:
        del env[key]
    else:
        env[key] = value
    with pytest.raises(ValueError, match=key):
        database.pool_options(env)


@pytest.mark.parametrize("port", ["0", "65536", "-1", "1.0", " 5432", "5432 ", "５４３２", "abc"])
def test_invalid_port_is_rejected(port):
    with pytest.raises(ValueError, match="DATABASE_PORT"):
        database.pool_options({**ENV, "DATABASE_PORT": port})


def test_pool_is_checked_before_returning(monkeypatch, environment):
    pool = fake_pool()
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr(asyncpg, "create_pool", factory)
    assert asyncio.run(database.open_pool()) is pool
    factory.assert_awaited_once_with(**database.pool_options(ENV))
    pool.fetchval.assert_awaited_once_with("SELECT 1")
    pool.close.assert_not_awaited()


def test_failed_readiness_closes_pool_and_hides_details(monkeypatch, environment):
    pool = fake_pool()
    pool.fetchval.side_effect = RuntimeError("secret:@/password at private-host")
    monkeypatch.setattr(asyncpg, "create_pool", AsyncMock(return_value=pool))
    with pytest.raises(RuntimeError, match="^database startup failed$"):
        asyncio.run(database.open_pool())
    pool.close.assert_awaited_once_with()


def test_failed_connection_hides_details(monkeypatch, environment):
    monkeypatch.setattr(asyncpg, "create_pool", AsyncMock(side_effect=OSError("private-host secret")))
    with pytest.raises(RuntimeError, match="^database startup failed$"):
        asyncio.run(database.open_pool())


def test_normal_shutdown_closes_without_termination():
    pool = fake_pool()
    asyncio.run(database.close_pool(pool))
    pool.close.assert_awaited_once_with()
    pool.terminate.assert_not_called()


def test_failed_shutdown_terminates_pool_and_reports_failure():
    pool = fake_pool()
    pool.close.side_effect = TimeoutError("private details")
    with pytest.raises(RuntimeError, match="^database shutdown failed$"):
        asyncio.run(database.close_pool(pool))
    pool.terminate.assert_called_once_with()


def test_cancelled_shutdown_terminates_pool_and_preserves_cancellation():
    pool = fake_pool()
    pool.close.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(database.close_pool(pool))
    pool.terminate.assert_called_once_with()
