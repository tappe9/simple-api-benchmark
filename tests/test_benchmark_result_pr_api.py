"""HTTP boundary tests never send real authenticated requests."""

import importlib
import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from benchmark.results import BenchmarkFailure


class ApiTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("benchmark.github_api")
        except ModuleNotFoundError:
            self.fail("bounded repository API client required")

    def test_fixed_repository_headers_json_and_explicit_write(self):
        module = self.module()
        api = module.GitHubAPI("test-secret")
        api.opener = Mock()
        api.opener.open.return_value = io.BytesIO(b'{"number":63}')
        self.assertEqual(api.request("POST", "pulls", {"title": "test"}), {"number": 63})
        args, kwargs = api.opener.open.call_args
        request = args[0]
        self.assertEqual(
            request.full_url, "https://api.github.com/repos/tappe9/simple-api-benchmark/pulls"
        )
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"title": "test"})
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertLessEqual(kwargs["timeout"], 30)

    def test_forbidden_urls_and_write_endpoints_never_reach_transport(self):
        api = self.module().GitHubAPI("test-secret")
        api.opener = Mock()
        for method, path in (
            ("GET", "https://attacker.invalid"),
            ("GET", "../other"),
            ("GET", "//attacker.invalid"),
            ("GET", "pulls\nAuthorization:x"),
            ("POST", "rulesets"),
            ("PUT", "git/refs/heads/main"),
            ("DELETE", "pulls/1"),
        ):
            with self.subTest(path=path), self.assertRaises(BenchmarkFailure):
                api.request(method, path)
        api.opener.open.assert_not_called()

    def test_http_transport_redirect_and_invalid_json_fail_without_secret_leak(self):
        module = self.module()
        api = module.GitHubAPI("test-secret")
        api.opener = Mock()
        for status in (301, 302, 401, 403, 404, 422, 500):
            api.opener.open.side_effect = HTTPError(
                "https://example", status, "test-secret", {}, None
            )
            with self.assertRaises(module.APIError) as error:
                api.request("POST", "pulls", {})
            self.assertEqual(error.exception.status, status)
            self.assertNotIn("test-secret", str(error.exception))
        api.opener.open.side_effect = URLError("test-secret")
        with self.assertRaises(module.APIError) as error:
            api.request("GET", "pulls")
        self.assertIsNone(error.exception.status)
        self.assertNotIn("test-secret", str(error.exception))
        api.opener.open.side_effect = None
        for content in (b"not JSON test-secret", b'{"x":1,"x":2}', b"x" * (module.MAX_BYTES + 1)):
            api.opener.open.return_value = io.BytesIO(content)
            with self.assertRaises(BenchmarkFailure):
                api.request("GET", "pulls")
        self.assertIsNone(
            module.NoRedirect().redirect_request(
                None, None, 302, "m", {}, "https://attacker.invalid"
            )
        )

    def test_pagination_is_complete_and_bounded_without_following_foreign_links(self):
        api = self.module().GitHubAPI("test-secret")
        api.request = Mock(
            side_effect=[
                {"jobs": [{}] * 100, "total_count": 101},
                {"jobs": [{}], "total_count": 101},
            ]
        )
        self.assertEqual(len(api.pages("actions/runs/1/attempts/1/jobs", "jobs")), 101)
        self.assertEqual(
            api.request.call_args_list[1].args,
            ("GET", "actions/runs/1/attempts/1/jobs?per_page=100&page=2"),
        )
        api.request = Mock(return_value={"jobs": [], "total_count": 1})
        with self.assertRaises(BenchmarkFailure):
            api.pages("actions/runs/1/attempts/1/jobs", "jobs")
        api.request = Mock(return_value=[{}] * 100)
        with self.assertRaises(BenchmarkFailure):
            api.pages("pulls", max_pages=2)
        self.assertEqual(api.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
