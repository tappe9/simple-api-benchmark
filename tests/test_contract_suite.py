"""Contract-document, real HTTP transport, repeatability and CLI checks."""

import contextlib
import io
import json
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from benchmark import contract_test as contract

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "API-CONTRACT.md"
VALUES = {
    "/health": (200, {"status": "ok"}),
    "/json": (200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]}),
    "/db/42": (200, {"id": 42, "name": "Item 42", "price": 4200}),
    "/db/999": (404, {"error": "not found"}),
    "/db/not-an-integer": (400, {"error": "invalid id"}),
    "/db/1.5": (400, {"error": "invalid id"}),
    "/cpu": (200, {"input": 30, "result": 832040}),
}
IMPLEMENTATIONS = ("go-gin", "rust-actix", "node-fastify", "python-fastapi")


@contextlib.contextmanager
def server(responder=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.request_version))
            try:
                if responder is not None:
                    responder(self)
                    return
                status, payload = VALUES[self.path]
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


class DocumentTests(unittest.TestCase):
    def test_cases_match_every_documented_response(self):
        cases = contract.load_cases()
        self.assertEqual(
            [(c.path, c.status, c.payload) for c in cases],
            [(path, status, payload) for path, (status, payload) in VALUES.items()],
        )
        self.assertTrue(all(c.content_type == "application/json" for c in cases))

    def test_expected_values_are_read_from_the_document_not_a_second_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.md"
            path.write_text(DOCUMENT.read_text().replace("Hello, World!", "Changed example"))
            cases = contract.load_cases(path)
            self.assertEqual(cases[1].payload["message"], "Changed example")

    def test_missing_extra_or_malformed_examples_fail_closed(self):
        text = DOCUMENT.read_text()
        documents = (
            text.replace("## `GET /cpu`", "## Removed CPU"),
            text + "\n## `GET /extra`\n",
            text.replace('"status": "ok"', '"status": "wrong", "status": "ok"'),
            text.replace('"status": "ok"', "broken json"),
            text.replace("HTTP/1.1 404 Not Found", "missing status"),
            text.replace("## `GET /json`", "```json\n{}\n```\n\n## `GET /json`"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.md"
            for text in documents:
                path.write_text(text)
                with self.subTest(document=text[-40:]), self.assertRaises(contract.ContractFailure):
                    contract.load_cases(path)


class SuiteTests(unittest.TestCase):
    def test_same_real_http_assertions_and_two_rounds_for_every_implementation(self):
        for implementation in IMPLEMENTATIONS:
            with (
                self.subTest(implementation=implementation),
                server() as (url, requests),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                count = contract.run_contract(url, implementation=implementation)
                self.assertEqual(count, 14)
                self.assertEqual(requests, [(path, "HTTP/1.1") for path in VALUES] * 2)
                self.assertIn(implementation, output.getvalue())

    def test_wrong_response_is_rejected_for_all_labels_and_stops_the_suite(self):
        for implementation in IMPLEMENTATIONS:
            wrong = contract.Response(200, "application/json", b'{"status":"wrong"}')
            with (
                self.subTest(implementation=implementation),
                patch.object(contract, "read_response", return_value=wrong) as read,
            ):
                with self.assertRaisesRegex(
                    contract.ContractFailure, rf"\[{implementation}\] GET /health:.*status.*value"
                ):
                    contract.run_contract("http://127.0.0.1:8080", implementation=implementation)
                self.assertEqual(read.call_count, 1)

    def test_second_round_changes_are_not_hidden(self):
        def respond(base_url, path, *, timeout):
            status, payload = VALUES[path]
            if respond.calls == 7:
                payload = {"status": "changed"}
            respond.calls += 1
            return contract.Response(status, "application/json", json.dumps(payload).encode())

        respond.calls = 0
        with (
            patch.object(contract, "read_response", side_effect=respond),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(contract.ContractFailure, r"GET /health:.*changed"):
                contract.run_contract("http://127.0.0.1:8080", implementation="go-gin")

    def test_cli_succeeds_and_reports_every_check(self):
        with server() as (url, requests):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "benchmark.contract_test",
                    "--base-url",
                    url,
                    "--implementation",
                    "go-gin",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(requests), 14)
        self.assertIn("14 checks passed", result.stdout)

    def test_cli_failure_prevents_a_chained_following_command(self):
        def wrong(handler):
            body = b'{"status":"wrong"}'
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        with server(wrong) as (url, _), tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "later-command-ran"
            check = shlex.join(
                [
                    sys.executable,
                    "-m",
                    "benchmark.contract_test",
                    "--base-url",
                    url,
                    "--implementation",
                    "python-fastapi",
                ]
            )
            after = shlex.join(
                [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
            )
            result = subprocess.run(
                ["sh", "-c", check + " && " + after],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("[python-fastapi] GET /health:", result.stderr)
            self.assertFalse(marker.exists(), "a failed contract must block the following command")


class TransportTests(unittest.TestCase):
    def test_non_http11_responses_and_duplicate_content_types_are_rejected(self):
        def invalid(handler):
            if invalid.kind == "protocol":
                handler.protocol_version = "HTTP/1.0"
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            if invalid.kind == "duplicate header":
                handler.send_header("Content-Type", "text/plain")
            handler.send_header("Content-Length", "2")
            handler.end_headers()
            handler.wfile.write(b"{}")

        for kind in ("protocol", "duplicate header"):
            invalid.kind = kind
            with (
                self.subTest(kind=kind),
                server(invalid) as (url, _),
                self.assertRaises(contract.ContractFailure),
            ):
                contract.read_response(url, "/health", timeout=1)

    def test_http_error_status_is_a_response_not_a_transport_exception(self):
        with server() as (url, _):
            for path, status in (("/db/999", 404), ("/db/not-an-integer", 400)):
                response = contract.read_response(url, path, timeout=1)
                self.assertEqual(response.status, status)

    def test_redirects_are_not_followed(self):
        def redirect(handler):
            handler.send_response(302)
            handler.send_header("Location", "/health")
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        with server(redirect) as (url, requests):
            response = contract.read_response(url, "/health", timeout=1)
        self.assertEqual(response.status, 302)
        self.assertEqual(len(requests), 1)

    def test_refused_connection_has_actionable_context(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
            with self.assertRaisesRegex(
                contract.ContractFailure, r"\[go-gin\] GET /health:.*transport"
            ):
                contract.run_contract(url, implementation="go-gin", timeout=0.2)

    def test_stalled_headers_have_a_bounded_timeout(self):
        def stall(handler):
            time.sleep(1)

        with server(stall) as (url, _):
            start = time.monotonic()
            with self.assertRaisesRegex(contract.ContractFailure, "timeout"):
                contract.read_response(url, "/health", timeout=0.15)
            self.assertLess(time.monotonic() - start, 0.8)

    def test_trickling_body_cannot_extend_the_response_deadline(self):
        def trickle(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", "1000")
            handler.end_headers()
            for _ in range(1000):
                handler.wfile.write(b" ")
                handler.wfile.flush()
                time.sleep(0.03)

        with server(trickle) as (url, _):
            start = time.monotonic()
            with self.assertRaisesRegex(contract.ContractFailure, "timeout"):
                contract.read_response(url, "/health", timeout=0.15)
            self.assertLess(time.monotonic() - start, 0.8)

    def test_oversized_response_is_rejected(self):
        def oversized(handler):
            body = b" " * (65536 + 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        with (
            server(oversized) as (url, _),
            self.assertRaisesRegex(contract.ContractFailure, "limit"),
        ):
            contract.read_response(url, "/health", timeout=1)

    def test_invalid_urls_and_nonfinite_or_nonpositive_timeouts_fail_before_io(self):
        for url in (
            "file:///tmp/api",
            "http://",
            "http://user:secret@localhost",
            "http://localhost?x=1",
            "http://localhost/#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(contract.ContractFailure):
                contract.read_response(url, "/health", timeout=1)
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(contract.ContractFailure):
                contract.read_response("http://127.0.0.1:8080", "/health", timeout=timeout)


if __name__ == "__main__":
    unittest.main()
