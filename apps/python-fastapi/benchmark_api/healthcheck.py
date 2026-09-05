"""Container readiness probe using only the Python standard library."""

import json
import urllib.request
from http.client import HTTPException


def check_health() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
            return (
                response.status == 200
                and response.headers.get_content_type() == "application/json"
                and json.loads(response.read(1025)) == {"status": "ok"}
            )
    except (OSError, ValueError, HTTPException):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if check_health() else 1)
