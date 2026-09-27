"""Gunicorn application-factory lifecycle tests."""

from unittest.mock import MagicMock

from benchmark_api import server


def test_factory_opens_worker_local_pool_and_registers_cleanup(monkeypatch):
    pool = object()
    app = object()
    open_pool = MagicMock(return_value=pool)
    close_pool = MagicMock()
    create_app = MagicMock(return_value=app)
    register = MagicMock()

    monkeypatch.setattr(server, "open_pool", open_pool)
    monkeypatch.setattr(server, "close_pool", close_pool)
    monkeypatch.setattr(server, "create_app", create_app)
    monkeypatch.setattr(server.atexit, "register", register)

    assert server.create_server_app() is app

    open_pool.assert_called_once_with()
    create_app.assert_called_once_with(pool)
    register.assert_called_once_with(close_pool, pool)
