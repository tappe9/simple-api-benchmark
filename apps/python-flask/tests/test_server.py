"""Waitress lifecycle tests for the approved one-process, one-thread profile."""

from unittest.mock import MagicMock

from benchmark_api import server


def test_server_uses_one_waitress_thread_and_closes_resources(monkeypatch):
    pool = object()
    waitress = MagicMock()
    waitress.run.return_value = None
    waitress.task_dispatcher = MagicMock()
    create_server = MagicMock(return_value=waitress)
    close_pool = MagicMock()
    monkeypatch.setattr(server, "open_pool", MagicMock(return_value=pool))
    monkeypatch.setattr(server, "close_pool", close_pool)
    monkeypatch.setattr(server, "create_server", create_server)
    monkeypatch.setattr(server, "create_app", MagicMock(return_value=object()))
    monkeypatch.setattr(server.signal, "signal", MagicMock(return_value=server.signal.SIG_DFL))

    server.serve()

    kwargs = create_server.call_args.kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8080
    assert kwargs["threads"] == 1
    waitress.run.assert_called_once_with()
    waitress.close.assert_called()
    waitress.task_dispatcher.shutdown.assert_called_once_with(cancel_pending=False, timeout=5)
    close_pool.assert_called_once_with(pool)
