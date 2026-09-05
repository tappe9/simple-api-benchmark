"""Ensure Rust-only acceptance assertions reject incorrect JSON numeric types."""

import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlsplit

import test_rust_actix_service as service


class JsonResponse(io.BytesIO):
    def __init__(self, status: int, payload: dict):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"


class AcceptanceTests(unittest.TestCase):
    def responses(self, replacement_path=None, replacement=None):
        def respond(request, timeout):
            self.assertGreater(timeout, 0)
            path = urlsplit(request.full_url).path
            values = {
                "/health": (200, {"status": "ok"}),
                "/json": (200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]}),
                "/db/42": (200, {"id": 42, "name": "Item 42", "price": 4200}),
                "/db/999": (404, {"error": "not found"}),
                "/db/not-an-integer": (400, {"error": "invalid id"}),
                "/cpu": (200, {"input": 30, "result": 832040}),
            }
            status, payload = values[path]
            if path == replacement_path:
                payload = replacement
            return JsonResponse(status, payload)
        return respond

    def test_valid_responses_are_accepted(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.responses()):
            service.check_endpoints()

    def test_boolean_cannot_replace_an_integer_array_element(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.responses(
            "/json", {"message": "Hello, World!", "items": [True, 2, 3, 4, 5]}
        )), self.assertRaises(service.CheckFailure):
            service.check_endpoints()

    def test_float_cannot_replace_a_database_integer(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.responses(
            "/db/42", {"id": 42.0, "name": "Item 42", "price": 4200}
        )), self.assertRaises(service.CheckFailure):
            service.check_endpoints()

    def test_float_cannot_replace_the_cpu_result(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.responses(
            "/cpu", {"input": 30, "result": 832040.0}
        )), self.assertRaises(service.CheckFailure):
            service.check_endpoints()


if __name__ == "__main__":
    unittest.main()
