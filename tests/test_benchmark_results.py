"""Pinned real oha output and deliberately corrupted results, never performance claims."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import results

FIXTURES = Path(__file__).parent / "fixtures" / "oha-1.16.0"


def fixture():
    return json.loads((FIXTURES / "timed.json").read_bytes())


def summary(index=1, rps=100.0):
    return {
        "run": index,
        "requests_per_second": rps,
        "mean_response_time_ms": index * 7.0,
        "peak_memory_bytes": index * 1024,
        "memory_samples": 3,
        "elapsed_seconds": 30.0,
        "successful_requests": int(rps * 30),
        "response_bytes": int(rps * 30) * 16,
    }


class ParserTests(unittest.TestCase):
    def test_actual_pinned_success_and_seconds_to_milliseconds(self):
        for name in ("success", "timed"):
            raw = (FIXTURES / (name + ".json")).read_bytes()
            actual = results.parse_oha(raw)
            expected = json.loads(raw)["summary"]
            self.assertEqual(actual["mean_response_time_ms"], expected["average"] * 1000)
            self.assertEqual(actual["requests_per_second"], expected["requestsPerSec"])
            self.assertEqual(
                actual["successful_requests"], json.loads(raw)["statusCodeDistribution"]["200"]
            )

    def test_real_http_error_and_timeout_are_invalid(self):
        for name in ("http-error", "timeout"):
            with self.subTest(name=name), self.assertRaises(results.BenchmarkFailure):
                results.parse_oha((FIXTURES / (name + ".json")).read_bytes())

    def test_required_fields_cannot_be_missing(self):
        original = fixture()
        for field in original:
            value = copy.deepcopy(original)
            del value[field]
            with self.subTest(field=field), self.assertRaises(results.BenchmarkFailure):
                results.parse_oha(json.dumps(value).encode())
        for field in original["summary"]:
            value = copy.deepcopy(original)
            del value["summary"][field]
            with self.subTest(metric=field), self.assertRaises(results.BenchmarkFailure):
                results.parse_oha(json.dumps(value).encode())

    def test_wrong_types_and_nonfinite_metrics_are_rejected(self):
        for field in fixture()["summary"]:
            for invalid in (True, False, None, "1", [], {}, -1, math.inf, math.nan):
                value = fixture()
                value["summary"][field] = invalid
                with (
                    self.subTest(field=field, invalid=invalid),
                    self.assertRaises(results.BenchmarkFailure),
                ):
                    results.parse_oha(json.dumps(value).encode())

    def test_wrong_counts_units_and_consistency_are_rejected(self):
        changes = [
            ("statusCodeDistribution", {"200": True}),
            ("statusCodeDistribution", {"200": 52.0}),
            ("statusCodeDistribution", {"200": 0}),
            ("statusCodeDistribution", {"200": 51, "500": 1}),
            ("errorDistribution", {"timeout": 0}),
            ("summary.successRate", 0.999),
            ("summary.requestsPerSec", 1000),
            ("summary.sizePerSec", 1000),
            ("summary.sizePerRequest", 16.0),
            ("summary.average", 39.432),
            ("metrics.latency_ms.mean", 0.039432),
            ("metrics.success_rate", True),
            ("responseTimeHistogram", {"NaN": 52}),
            ("responseTimeHistogram", {"0.1": True}),
            ("latencyPercentiles.p99", float("inf")),
            ("details.DNSLookup.average", float("nan")),
            ("summary.totalData", 10**400),
            ("rps.mean", 10**20),
            ("rps.percentiles.p50", 10**20),
            ("responseTimeHistogram", {"100000": 52}),
        ]
        for path, replacement in changes:
            value = fixture()
            target = value
            keys = path.split(".")
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(results.BenchmarkFailure):
                results.parse_oha(json.dumps(value).encode())

    def test_json_structure_duplicates_and_overflow_are_rejected(self):
        for raw in (
            b"[]",
            b"null",
            b"true",
            b"{}",
            b"{",
            b'{"x":1,"x":2}',
            b'{"x":1e999}',
            b"\xff",
        ):
            with self.subTest(raw=raw), self.assertRaises(results.BenchmarkFailure):
                results.parse_oha(raw)

    def test_expected_duration_is_checked_not_assumed(self):
        raw = (FIXTURES / "timed.json").read_bytes()
        results.parse_oha(raw, duration=1)
        with self.assertRaisesRegex(results.BenchmarkFailure, "duration"):
            results.parse_oha(raw, duration=30)
        value = fixture()
        value["summary"]["total"] = 30
        value["summary"]["requestsPerSec"] = 52 / 30
        value["summary"]["sizePerSec"] = 832 / 30
        value["metrics"]["requests_per_sec"] = 52 / 30
        with self.assertRaisesRegex(results.BenchmarkFailure, "duration"):
            results.parse_oha(json.dumps(value).encode(), duration=1, request_timeout=15)


class SelectionTests(unittest.TestCase):
    def test_selects_middle_throughput_with_all_metrics_from_that_run(self):
        runs = [summary(1, 10500), summary(2, 9900), summary(3, 10100)]
        self.assertEqual(results.select_run(runs), runs[2])

    def test_ties_are_stable_by_run_number(self):
        runs = [summary(3, 100), summary(1, 100), summary(2, 100)]
        self.assertEqual(results.select_run(runs), summary(2, 100))

    def test_exactly_three_distinct_valid_runs_required(self):
        good = [summary(i) for i in (1, 2, 3)]
        bad_sets = [[], good[:2], good + [summary(4)], [good[0]] * 3]
        for field in (
            "run",
            "requests_per_second",
            "mean_response_time_ms",
            "peak_memory_bytes",
            "memory_samples",
        ):
            for invalid in (True, None, -1, float("inf")):
                changed = copy.deepcopy(good)
                changed[1][field] = invalid
                bad_sets.append(changed)
        for runs in bad_sets:
            with self.subTest(runs=runs), self.assertRaises(results.BenchmarkFailure):
                results.select_run(runs)


class AtomicSaveTests(unittest.TestCase):
    def test_replace_failure_leaves_existing_bytes_and_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "latest.json"
            destination.write_bytes(b"existing verified result")
            with patch.object(results.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    results.atomic_json(destination, {"new": "result"})
            self.assertEqual(destination.read_bytes(), b"existing verified result")
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_nonfinite_cannot_replace_existing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "latest.json"
            destination.write_text("old")
            with self.assertRaises(ValueError):
                results.atomic_json(destination, {"bad": math.nan})
            self.assertEqual(destination.read_text(), "old")
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_success_writes_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "results" / "latest.json"
            results.atomic_json(destination, {"complete": [1, 2, 3]})
            self.assertEqual(json.loads(destination.read_text()), {"complete": [1, 2, 3]})
