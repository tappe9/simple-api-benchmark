"""Container readiness probe."""

import urllib.request


def check_health() -> bool:
    raise NotImplementedError
