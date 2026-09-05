"""The shared HTTP contract, using ordinary Python values for JSON responses."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from benchmark_api import database

ITEM_QUERY = "SELECT id, name, price FROM items WHERE id = $1"
SIGNED_DECIMAL = re.compile(r"[+-]?[0-9]+")


def parse_id(value: str) -> int:
    """Validate an ASCII signed BIGINT before acquiring a database connection."""
    if SIGNED_DECIMAL.fullmatch(value) is None:
        raise ValueError("invalid id")
    digits = value.lstrip("+-").lstrip("0") or "0"
    # Bound conversion work, including Python's integer-string length limit.
    if len(digits) > 19:
        raise ValueError("invalid id")
    number = int(digits)
    if value.startswith("-"):
        number = -number
    if not -(2**63) <= number <= 2**63 - 1:
        raise ValueError("invalid id")
    return number


def fibonacci(n: int) -> int:
    """Intentionally naive recursion: every request performs the same work."""
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await database.open_pool()
    app.state.pool = pool
    try:
        yield
    finally:
        await database.close_pool(pool)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/json")
    async def json_response() -> dict[str, str | list[int]]:
        return {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]}

    @app.get("/db/{id}")
    async def db_item(id: str, response: Response) -> dict[str, str | int]:
        try:
            item_id = parse_id(id)
        except ValueError:
            response.status_code = 400
            return {"error": "invalid id"}

        try:
            row = await app.state.pool.fetchrow(ITEM_QUERY, item_id)
            if row is not None:
                return {"id": row["id"], "name": row["name"], "price": row["price"]}
        except Exception:
            # Do not expose connection details, SQL, or driver exception text.
            response.status_code = 500
            return {"error": "internal server error"}

        response.status_code = 404
        return {"error": "not found"}

    @app.get("/cpu")
    async def cpu() -> dict[str, int]:
        return {"input": 30, "result": fibonacci(30)}

    return app


app = create_app()
