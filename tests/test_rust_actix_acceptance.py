"""Regression tests for Rust-only JSON and container acceptance assertions."""

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


class ContainerProcessTests(unittest.TestCase):
    def run_commands(self, process_rows):
        state = {
            "State": {"Health": {"Status": "healthy"}},
            "RestartCount": 0,
            "HostConfig": {
                "NanoCpus": 1000000000, "Memory": 536870912,
                "RestartPolicy": {"Name": "no"}, "Privileged": False,
                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
            },
            "Config": {"User": "65532:65532"},
            "Path": "/usr/local/bin/rust-actix", "Args": [],
            "NetworkSettings": {"Ports": {
                "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}],
            }},
        }

        def execute(command, **kwargs):
            if command == ["docker", "compose", "ps", "--quiet", "rust-actix"]:
                output = "container-id\n"
            elif command == ["docker", "inspect", "container-id"]:
                output = json.dumps([state])
            elif command[:2] == ["docker", "top"]:
                self.assertEqual(command, ["docker", "top", "container-id", "-eo", "pid,args"])
                output = "PID COMMAND\n" + process_rows
            elif command[:3] == ["docker", "compose", "exec"]:
                output = ""
            else:
                self.fail(f"unexpected command: {command}")
            return service.subprocess.CompletedProcess(command, 0, output, "")
        return execute

    def test_one_server_with_healthcheck_is_accepted(self):
        processes = "8824 /usr/local/bin/rust-actix\n9000 /usr/local/bin/rust-actix healthcheck\n"
        with patch.object(service, "run", side_effect=self.run_commands(processes)):
            self.assertEqual(service.check_container_contract(), "container-id")

    def test_multiple_servers_are_rejected(self):
        processes = "8824 /usr/local/bin/rust-actix\n9000 /usr/local/bin/rust-actix\n"
        with patch.object(service, "run", side_effect=self.run_commands(processes)):
            with self.assertRaisesRegex(service.CheckFailure, "expected one server process"):
                service.check_container_contract()

    def test_missing_server_is_rejected(self):
        with patch.object(service, "run", side_effect=self.run_commands("9000 sleep 1\n")):
            with self.assertRaisesRegex(service.CheckFailure, "expected one server process"):
                service.check_container_contract()


if __name__ == "__main__":
    unittest.main()
