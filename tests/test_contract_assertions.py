"""Adversarial checks for the shared response assertions themselves."""

import json
import unittest

from benchmark import contract_test as contract


class AssertionTests(unittest.TestCase):
    case = contract.Case("/json", 200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})

    def response(self, payload=None, *, status=200, content_type="application/json", body=None):
        if body is None:
            body = json.dumps(self.case.payload if payload is None else payload).encode()
        return contract.Response(status, content_type, body)

    def test_accepts_exact_object_with_reordered_keys_and_whitespace(self):
        contract.assert_response(
            self.case,
            self.response(body=(b' { "items" : [1, 2, 3, 4, 5], "message" : "Hello, World!" } \n')),
            "go-gin",
        )

    def test_accepts_json_media_type_parameters_and_case(self):
        for value in ("application/json", "application/json; charset=utf-8", "Application/JSON"):
            with self.subTest(value=value):
                contract.assert_response(self.case, self.response(content_type=value), "rust-actix")

    def test_rejects_wrong_status(self):
        for status in (201, 301, 400, 404, 500):
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(contract.ContractFailure, "status"),
            ):
                contract.assert_response(self.case, self.response(status=status), "go-gin")

    def test_rejects_wrong_or_missing_content_type(self):
        for value in ("", "text/html", "application/jsonp", "application/problem+json"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(contract.ContractFailure, "Content-Type"),
            ):
                contract.assert_response(
                    self.case, self.response(content_type=value), "node-fastify"
                )

    def test_rejects_non_objects_and_wrong_fields(self):
        payloads = [
            [],
            True,
            1,
            "ok",
            {},
            {"message": "Hello, World!"},
            {**self.case.payload, "framework": "extra"},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(contract.ContractFailure):
                contract.assert_response(self.case, self.response(payload), "python-fastapi")

    def test_rejects_wrong_values_and_array_order_or_length(self):
        for payload in (
            {**self.case.payload, "message": "wrong"},
            {**self.case.payload, "items": [1, 2, 3, 4]},
            {**self.case.payload, "items": [1, 2, 3, 4, 5, 6]},
            {**self.case.payload, "items": [5, 4, 3, 2, 1]},
        ):
            with self.subTest(payload=payload), self.assertRaises(contract.ContractFailure):
                contract.assert_response(self.case, self.response(payload), "go-gin")

    def test_rejects_boolean_float_string_and_null_in_integer_array(self):
        for value in (True, 1.0, "1", None):
            payload = {**self.case.payload, "items": [value, 2, 3, 4, 5]}
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(contract.ContractFailure, r"items\[0\].*type"),
            ):
                contract.assert_response(self.case, self.response(payload), "python-fastapi")

    def test_rejects_float_and_boolean_database_and_cpu_numbers(self):
        for path, payload in (
            ("/db/42", {"id": 42, "name": "Item 42", "price": 4200}),
            ("/cpu", {"input": 30, "result": 832040}),
        ):
            case = contract.Case(path, 200, payload)
            for key, value in payload.items():
                if type(value) is not int:
                    continue
                for wrong in (float(value), True, str(value), None):
                    response = contract.Response(
                        200, "application/json", json.dumps({**payload, key: wrong}).encode()
                    )
                    with (
                        self.subTest(path=path, key=key, value=wrong),
                        self.assertRaises(contract.ContractFailure),
                    ):
                        contract.assert_response(case, response, "rust-actix")

    def test_rejects_wrong_error_body_even_when_status_is_correct(self):
        for path, status, error in (
            ("/db/999", 404, "not found"),
            ("/db/not-an-integer", 400, "invalid id"),
        ):
            case = contract.Case(path, status, {"error": error})
            for payload in (
                {"error": "wrong"},
                {"detail": error},
                {"error": error, "status": status},
            ):
                response = contract.Response(
                    status, "application/json", json.dumps(payload).encode()
                )
                with (
                    self.subTest(path=path, payload=payload),
                    self.assertRaises(contract.ContractFailure),
                ):
                    contract.assert_response(case, response, "node-fastify")

    def test_rejects_malformed_json_duplicate_keys_and_nonfinite_numbers(self):
        for body in (
            b"{",
            b"null",
            b"{} {}",
            b"\xff",
            b'{"message":"wrong","message":"Hello, World!","items":[1,2,3,4,5]}',
            b'{"message":"Hello, World!","items":[NaN,2,3,4,5]}',
            b'{"message":"Hello, World!","items":[Infinity,2,3,4,5]}',
        ):
            with self.subTest(body=body), self.assertRaises(contract.ContractFailure):
                contract.assert_response(self.case, self.response(body=body), "python-fastapi")

    def test_diagnostics_identify_implementation_endpoint_and_field(self):
        payload = {**self.case.payload, "items": [True, 2, 3, 4, 5]}
        with self.assertRaisesRegex(
            contract.ContractFailure, r"\[python-fastapi\] GET /json:.*items\[0\]"
        ):
            contract.assert_response(self.case, self.response(payload), "python-fastapi")


if __name__ == "__main__":
    unittest.main()
