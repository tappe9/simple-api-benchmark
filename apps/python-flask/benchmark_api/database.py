"""Synchronous psycopg pool with bounded startup, query, and shutdown behavior."""

import os
import re
from collections.abc import Mapping

from psycopg import conninfo
from psycopg_pool import ConnectionPool

ITEM_QUERY = "SELECT id, name, price FROM items WHERE id = %s"


def pool_settings(env: Mapping[str, str]) -> tuple[str, dict]:
    required = (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
    )
    for key in required:
        if not env.get(key):
            raise ValueError(f"{key} is required")
    port_text = env["DATABASE_PORT"]
    if re.fullmatch(r"[0-9]{1,5}", port_text) is None or not 1 <= int(port_text) <= 65535:
        raise ValueError("DATABASE_PORT must be an integer between 1 and 65535")
    dsn = conninfo.make_conninfo(
        host=env["DATABASE_HOST"],
        port=int(port_text),
        dbname=env["DATABASE_NAME"],
        user=env["DATABASE_USER"],
        password=env["DATABASE_PASSWORD"],
        connect_timeout=5,
    )
    return dsn, {"min_size": 1, "max_size": 10, "timeout": 5, "open": False}


def open_pool() -> ConnectionPool:
    """Open the pool and prove PostgreSQL readiness before HTTP starts."""
    pool = None
    try:
        dsn, options = pool_settings(os.environ)
        pool = ConnectionPool(dsn, **options)
        pool.open(wait=True, timeout=5)
        with pool.connection(timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
        if row != (1,):
            raise RuntimeError("unexpected readiness result")
        return pool
    except Exception:
        if pool is not None:
            try:
                pool.close(timeout=5)
            except Exception:
                pass
        raise RuntimeError("database startup failed") from None


def fetch_item(pool: ConnectionPool, item_id: int):
    with pool.connection(timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(ITEM_QUERY, (item_id,))
            return cursor.fetchone()


def close_pool(pool: ConnectionPool) -> None:
    try:
        pool.close(timeout=5)
    except Exception:
        raise RuntimeError("database shutdown failed") from None
