"""HTTP application."""

from fastapi import FastAPI


def fibonacci(n: int) -> int:
    raise NotImplementedError


def create_app() -> FastAPI:
    return FastAPI()


app = create_app()
