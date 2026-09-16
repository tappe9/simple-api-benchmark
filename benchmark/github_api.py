"""Bounded JSON-only repository API; no redirects, token logging or write retries."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .report import REPOSITORY
from .results import BenchmarkFailure, require, strict_json

MAX_BYTES = 4 * 1024 * 1024


class APIError(BenchmarkFailure):
    def __init__(self, status: int | None):
        self.status = status
        super().__init__(
            f"GitHub API failed (HTTP {status})" if status else "GitHub API transport failed"
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    def __init__(self, token: str):
        require(
            type(token) is str and bool(token) and not any(c.isspace() for c in token),
            "API token required",
        )
        self._token = token
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, body=None):
        require(type(path) is str and bool(path) and not path.startswith("/"), "invalid API path")
        require(re.fullmatch(r"[A-Za-z0-9_./?=&%+:-]+", path) is not None, "invalid API path")
        require(".." not in path and "://" not in path and "//" not in path, "invalid API path")
        allowed = (
            method == "GET"
            or (method == "POST" and path == "pulls")
            or (method == "PUT" and re.fullmatch(r"pulls/[1-9][0-9]*/merge", path))
        )
        require(bool(allowed), "unsupported API write")
        request = Request(
            f"https://api.github.com/repos/{REPOSITORY}/{path}",
            data=None if body is None else json.dumps(body, allow_nan=False).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "simple-api-benchmark-result-publisher",
            },
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
        except HTTPError as error:
            raise APIError(error.code) from None
        except (URLError, OSError, TimeoutError):
            raise APIError(None) from None
        require(len(raw) <= MAX_BYTES, "API response exceeds limit")
        try:
            return strict_json(raw)
        except (BenchmarkFailure, ValueError, UnicodeError):
            raise BenchmarkFailure("invalid JSON API response") from None

    def pages(self, path: str, key: str | None = None, *, max_pages: int = 30) -> list:
        items = []
        total = None
        for page in range(1, max_pages + 1):
            separator = "&" if "?" in path else "?"
            response = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if key is None:
                batch = response
            else:
                require(type(response) is dict and key in response, "malformed API collection")
                batch = response[key]
                count = response.get("total_count")
                require(type(count) is int and count >= 0, "missing API collection count")
                require(total is None or total == count, "API collection changed during pagination")
                total = count
            require(type(batch) is list and len(batch) <= 100, "malformed API collection")
            items.extend(batch)
            if len(batch) < 100:
                require(total is None or len(items) == total, "incomplete API collection")
                return items
        raise BenchmarkFailure("API pagination limit exceeded")
