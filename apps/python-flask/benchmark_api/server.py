"""Gunicorn application factory with worker-local database resources."""

import atexit

from benchmark_api.app import create_app
from benchmark_api.database import close_pool, open_pool


def create_server_app():
    """Create one worker-local Flask app and close its pool when the worker exits."""
    pool = open_pool()
    atexit.register(close_pool, pool)
    return create_app(pool)
