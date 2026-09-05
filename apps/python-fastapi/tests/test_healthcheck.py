"""Focused readiness probe tests."""

import io
from unittest.mock import MagicMock

import pytest

from benchmark_api import healthcheck


@pytest.mark.parametrize("status, content_type, body, expected", [
    (200, "application/json", b'{"status":"ok"}', True),
    (500, "application/json", b'{"status":"ok"}', False),
    (200, "text/plain", b'{"status":"ok"}', False),
    (200, "application/json", b'{"status":"bad"}', False),
    (200, "application/json", b'{"status":"ok","extra":1}', False),
    (200, "application/json", b'not json', False),
])
def test_probe_validates_status_type_and_body(monkeypatch, status, content_type, body, expected):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = status
    response.headers.get_content_type.return_value = content_type
    response.read.side_effect = io.BytesIO(body).read
    opener = MagicMock(return_value=response)
    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", opener)
    assert healthcheck.check_health() is expected
    opener.assert_called_once_with("http://127.0.0.1:8080/health", timeout=2)


@pytest.mark.parametrize("error", [TimeoutError(), OSError("unreachable")])
def test_probe_fails_closed_on_network_errors(monkeypatch, error):
    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", MagicMock(side_effect=error))
    assert healthcheck.check_health() is False
