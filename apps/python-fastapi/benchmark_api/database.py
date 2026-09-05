"""Shared PostgreSQL settings and a bounded, startup-checked asyncpg pool."""

import asyncio
import os
import re
from collections.abc import Mapping
from typing import Any

import asyncpg


def pool_options(env: Mapping[str, str]) -> dict[str, Any]:
    required = ("DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD")
    for key in required:
        if not env.get(key):
            raise ValueError(f"{key} is required")
    port_text = env["DATABASE_PORT"]
    if re.fullmatch(r"[0-9]{1,5}", port_text) is None or not 1 <= int(port_text) <= 65535:
        raise ValueError("DATABASE_PORT must be an integer between 1 and 65535")
    return {
        "host": env["DATABASE_HOST"],
        "port": int(port_text),
        "database": env["DATABASE_NAME"],
        "user": env["DATABASE_USER"],
        "password": env["DATABASE_PASSWORD"],
        "min_size": 1,
        "max_size": 10,
        "timeout": 5,
        "command_timeout": 5,
        "ssl": False,
    }


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close connections normally, with a bounded fallback on failure."""
    try:
        await asyncio.wait_for(pool.close(), timeout=5)
    except asyncio.CancelledError:
        pool.terminate()
        raise
    except Exception:
        pool.terminate()
        raise RuntimeError("database shutdown failed") from None


async def open_pool() -> asyncpg.Pool:
    """Refuse to serve HTTP until a real PostgreSQL query has succeeded."""
    pool = None
    try:
        pool = await asyncpg.create_pool(**pool_options(os.environ))
        if await pool.fetchval("SELECT 1") != 1:
            raise RuntimeError("unexpected readiness result")
        return pool
    except asyncio.CancelledError:
        if pool is not None:
            pool.terminate()
        raise
    except Exception:
        if pool is not None:
            try:
                await close_pool(pool)
            except RuntimeError:
                pass
        raise RuntimeError("database startup failed") from None
