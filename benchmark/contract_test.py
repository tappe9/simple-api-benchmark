"""The executable shared HTTP contract."""

import argparse
import http.client
import json
import math
import re
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ContractFailure(RuntimeError):
    """An API response does not satisfy the documented contract."""


@dataclass(frozen=True)
class Case:
    path: str
    status: int
    payload: dict
    content_type: str = "application/json"


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes


def assert_response(case: Case, response: Response, implementation: str) -> None:
    prefix = f"[{implementation}] GET {case.path}:"
    try:
        if response.status != case.status:
            raise ContractFailure(f"status: expected {case.status}, got {response.status}")
        media_type = response.content_type.split(";", 1)[0].strip().lower()
        if media_type != case.content_type.lower():
            raise ContractFailure(
                f"Content-Type: expected {case.content_type}, got {response.content_type!r}"
            )
        try:
            payload = decode_json(response.body)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ContractFailure(f"invalid JSON: {error}") from error
        compare_json(payload, case.payload)
    except ContractFailure as error:
        raise ContractFailure(f"{prefix} {error}") from error


def decode_json(body: bytes):
    """Reject duplicate keys and non-JSON constants instead of silently normalizing them."""

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-JSON number {value}")

    return json.loads(
        body.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=invalid_constant
    )


def compare_json(actual, expected, location: str = "$") -> None:
    """Compare structure, exact types and values without Python's bool == int shortcut."""
    if type(actual) is not type(expected):
        raise ContractFailure(
            f"{location} type: expected {type(expected).__name__}, got {type(actual).__name__}"
        )
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise ContractFailure(
                f"{location} keys: expected {sorted(expected)}, got {sorted(actual)}"
            )
        for key, value in expected.items():
            compare_json(actual[key], value, f"{location}.{key}")
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ContractFailure(f"{location} length: expected {len(expected)}, got {len(actual)}")
        for index, (value, wanted) in enumerate(zip(actual, expected)):
            compare_json(value, wanted, f"{location}[{index}]")
    elif actual != expected:
        raise ContractFailure(f"{location} value: expected {expected!r}, got {actual!r}")


DOCUMENT = Path(__file__).resolve().parents[1] / "docs" / "API-CONTRACT.md"
MAX_BODY_BYTES = 65536
# Request examples, not response expectations: all expected values come from DOCUMENT.
ENDPOINTS = {
    "/health": ("/health",),
    "/json": ("/json",),
    "/db/{id}": ("/db/42", "/db/999", "/db/not-an-integer"),
    "/cpu": ("/cpu",),
}


def load_cases(document: Path = DOCUMENT) -> tuple[Case, ...]:
    """Read the six documented response examples; fail closed on format/coverage drift."""
    try:
        text = document.read_text(encoding="utf-8")
        sections = re.split(r"^## ", text, flags=re.MULTILINE)
        api_sections = {}
        for section in sections:
            heading, _, body = section.partition("\n")
            if heading.startswith("`GET "):
                endpoint = heading.removeprefix("`GET ").removesuffix("`")
                if endpoint in api_sections:
                    raise ValueError(f"duplicate endpoint {endpoint}")
                api_sections[endpoint] = body
        if api_sections.keys() != ENDPOINTS.keys():
            raise ValueError("expected exactly /health, /json, /db/{id}, and /cpu sections")
        cases = []
        pattern = re.compile(
            r"^```http\nHTTP/1\.1 (\d{3})[^\n]*\n([^`]+?)\n```\s*"
            r"^```json\n(.*?)\n```",
            re.MULTILINE | re.DOTALL,
        )
        for endpoint, paths in ENDPOINTS.items():
            section = api_sections[endpoint]
            examples = pattern.findall(section)
            json_blocks = re.findall(r"^```json\s*$", section, re.MULTILINE)
            if len(examples) != len(paths) or len(json_blocks) != len(paths):
                raise ValueError(f"{endpoint}: expected {len(paths)} paired HTTP/JSON examples")
            for path, (status, headers, body) in zip(paths, examples):
                content_types = re.findall(r"^Content-Type: (.+)$", headers, re.MULTILINE)
                if len(content_types) != 1 or content_types[0] != "application/json":
                    raise ValueError(f"{endpoint}: expected one application/json content type")
                payload = decode_json(body.encode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError(f"{endpoint}: response example must be an object")
                case = Case(path, int(status), payload, content_types[0])
                cases.append(case)
                if path == "/db/not-an-integer":
                    cases.append(Case("/db/1.5", case.status, case.payload, case.content_type))
        return tuple(cases)
    except (OSError, ValueError, RecursionError) as error:
        raise ContractFailure(f"contract document {document}: {error}") from error


def read_response(base_url: str, path: str, *, timeout: float) -> Response:
    """Use HTTP/1.1 without redirects, with connect and whole-response deadlines."""
    try:
        url = urlsplit(base_url)
        port = url.port
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("base URL must be HTTP(S), without credentials, query, or fragment")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
    except ValueError as error:
        raise ContractFailure(f"transport configuration: {error}") from error
    connection_type = (
        http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(url.hostname, port, timeout=timeout)
    timer = None
    expired = threading.Event()
    try:
        connection.connect()
        connected_socket = connection.sock

        def abort_response():
            expired.set()
            try:
                connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # A per-read timeout alone can be extended forever by trickling bytes.
        timer = threading.Timer(timeout, abort_response)
        timer.daemon = True
        timer.start()
        connection.request(
            "GET",
            url.path.rstrip("/") + path,
            headers={"Accept": "application/json", "Connection": "close"},
        )
        with connection.getresponse() as response:
            if response.version != 11:
                raise ContractFailure("transport: expected an HTTP/1.1 response")
            content_types = response.headers.get_all("Content-Type", [])
            if len(content_types) > 1:
                raise ContractFailure("Content-Type: duplicate headers")
            body = response.read(MAX_BODY_BYTES + 1)
            if expired.is_set():
                raise TimeoutError("response deadline exceeded")
            if len(body) > MAX_BODY_BYTES:
                raise ContractFailure(f"response body exceeds {MAX_BODY_BYTES}-byte limit")
            return Response(response.status, response.getheader("Content-Type", ""), body)
    except (OSError, http.client.HTTPException) as error:
        reason = "timeout" if expired.is_set() or isinstance(error, TimeoutError) else str(error)
        raise ContractFailure(f"transport: {reason}") from error
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        connection.close()


def run_contract(base_url: str, *, implementation: str = "custom", timeout: float = 5.0) -> int:
    """Fail fast; callers must not measure a backend when this function raises."""
    cases = load_cases()
    checks = 0
    for repetition in range(1, 3):
        for case in cases:
            try:
                response = read_response(base_url, case.path, timeout=timeout)
            except ContractFailure as error:
                raise ContractFailure(f"[{implementation}] GET {case.path}: {error}") from error
            assert_response(case, response, implementation)
            checks += 1
            print(f"[{implementation}] GET {case.path}: PASS (round {repetition}/2)", flush=True)
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--implementation", default="custom", help="diagnostic label, never changes assertions"
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="connect and response deadlines in seconds"
    )
    args = parser.parse_args(argv)
    try:
        checks = run_contract(
            args.base_url, implementation=args.implementation, timeout=args.timeout
        )
    except (ContractFailure, KeyboardInterrupt) as error:
        print(f"Contract failed: {error}", file=sys.stderr)
        return 1
    print(f"[{args.implementation}] {checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
