"""Health probe behavior."""

from unittest.mock import MagicMock

from benchmark_api import healthcheck


def test_healthcheck_accepts_exact_healthy_response(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'{"status":"ok"}'
    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", MagicMock(return_value=response))
    monkeypatch.setattr(healthcheck.json, "load", MagicMock(return_value={"status": "ok"}))
    assert healthcheck.main() == 0


def test_healthcheck_fails_closed(monkeypatch):
    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", MagicMock(side_effect=OSError("down")))
    assert healthcheck.main() == 1
