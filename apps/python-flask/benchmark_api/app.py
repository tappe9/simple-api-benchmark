"""Flask implementation of the shared HTTP benchmark contract."""

import re

from flask import Flask

from benchmark_api import database

SIGNED_DECIMAL = re.compile(r"[+-]?[0-9]+")


def parse_id(value: str) -> int:
    """Parse an ASCII signed PostgreSQL BIGINT without accepting alternate syntaxes."""
    if SIGNED_DECIMAL.fullmatch(value) is None:
        raise ValueError("invalid id")
    digits = value.lstrip("+-").lstrip("0") or "0"
    if len(digits) > 19:
        raise ValueError("invalid id")
    number = int(digits)
    if value.startswith("-"):
        number = -number
    if not -(2**63) <= number <= 2**63 - 1:
        raise ValueError("invalid id")
    return number


def fibonacci(n: int) -> int:
    """Intentionally naive recursion performed for every CPU request."""
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def create_app(pool) -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/json")
    def json_response():
        return {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]}

    @app.get("/db/<path:item_id>")
    def db_item(item_id: str):
        try:
            parsed = parse_id(item_id)
        except ValueError:
            return {"error": "invalid id"}, 400
        try:
            row = database.fetch_item(pool, parsed)
        except Exception:
            return {"error": "internal server error"}, 500
        if row is None:
            return {"error": "not found"}, 404
        return {"id": row[0], "name": row[1], "price": row[2]}

    @app.get("/cpu")
    def cpu():
        return {"input": 30, "result": fibonacci(30)}

    return app
