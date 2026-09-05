"""Validate the pinned oha JSON contract and publish complete results atomically."""

import json
import math
import os
import tempfile
from pathlib import Path

from .contract_test import ContractFailure, decode_json


class BenchmarkFailure(RuntimeError):
    """An invalid measurement or a failed benchmark operation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkFailure(message)


def number(value, label: str, *, integer: bool = False, positive: bool = False):
    valid_type = type(value) is int if integer else type(value) in (int, float)
    require(
        valid_type,
        f"{label}: expected {'integer' if integer else 'number'}, not {type(value).__name__}",
    )
    require(
        (abs(value) <= 2**64 - 1 if type(value) is int else math.isfinite(value))
        and (value > 0 if positive else value >= 0),
        f"{label}: expected finite {'positive' if positive else 'nonnegative'} value",
    )
    return value


def object_fields(value, fields, label):
    require(type(value) is dict, f"{label}: expected object")
    require(set(value) == set(fields), f"{label}: expected fields {sorted(fields)}")
    return value


def close(actual, expected, label, *, tolerance=1e-8):
    require(
        math.isclose(actual, expected, rel_tol=tolerance, abs_tol=1e-9),
        f"{label}: inconsistent value or unit",
    )


def strict_json(raw: bytes):
    try:
        return decode_json(raw)
    except (ContractFailure, ValueError, RecursionError) as error:
        raise BenchmarkFailure(f"invalid JSON: {error}") from error


def parse_oha(raw: bytes, *, duration: float | None = None, request_timeout: float = 15) -> dict:
    """oha 1.16.0 print_json: summary durations are seconds; latency_ms is rounded.

    requestsPerSec counts *all* attempts, so it is usable as successful throughput
    only after rejecting every transport error and non-200 status. No defaults
    substitute for missing fields. The schema is deliberately version-specific.
    """
    data = object_fields(
        strict_json(raw),
        (
            "summary",
            "metrics",
            "responseTimeHistogram",
            "latencyPercentiles",
            "firstByteHistogram",
            "firstBytePercentiles",
            "rps",
            "details",
            "statusCodeDistribution",
            "errorDistribution",
        ),
        "oha",
    )
    object_fields(
        data["errorDistribution"], (), "errorDistribution (errors/timeouts invalidate run)"
    )
    statuses = object_fields(data["statusCodeDistribution"], ("200",), "statusCodeDistribution")
    count = number(statuses["200"], "HTTP 200 count", integer=True, positive=True)
    s = object_fields(
        data["summary"],
        (
            "successRate",
            "total",
            "slowest",
            "fastest",
            "average",
            "requestsPerSec",
            "totalData",
            "sizePerRequest",
            "sizePerSec",
        ),
        "summary",
    )
    for name, value in s.items():
        number(
            value, "summary." + name, integer=name in ("totalData", "sizePerRequest"), positive=True
        )
    require(s["successRate"] == 1, "successRate: errors/timeouts invalidate run")
    require(
        s["fastest"] <= s["average"] <= s["slowest"] <= s["total"],
        "summary: inconsistent response durations",
    )
    close(s["requestsPerSec"], count / s["total"], "requestsPerSec")
    close(s["sizePerSec"], s["totalData"] / s["total"], "sizePerSec")
    require(
        s["sizePerRequest"] == s["totalData"] // count, "sizePerRequest: inconsistent byte count"
    )
    if duration is not None:
        number(duration, "duration", positive=True)
        number(request_timeout, "request timeout", positive=True)
        require(
            duration <= s["total"] <= duration + request_timeout + 2,
            f"duration: expected {duration}s sending plus bounded request drain, got {s['total']}s",
        )

    percentile_names = ("p10", "p25", "p50", "p75", "p90", "p95", "p99", "p99.9", "p99.99")
    for field in ("latencyPercentiles", "firstBytePercentiles"):
        percentiles = object_fields(data[field], percentile_names, field)
        values = [number(percentiles[name], f"{field}.{name}") for name in percentile_names]
        require(
            values == sorted(values) and values[-1] <= s["total"], f"{field}: invalid order/range"
        )
    for field in ("responseTimeHistogram", "firstByteHistogram"):
        histogram = data[field]
        require(type(histogram) is dict and bool(histogram), f"{field}: expected nonempty object")
        for label, value in histogram.items():
            try:
                bucket = float(label)
            except (TypeError, ValueError) as error:
                raise BenchmarkFailure(f"{field}: invalid bucket {label!r}") from error
            number(bucket, field + " bucket")
            require(bucket <= s["total"], f"{field}: bucket exceeds elapsed time")
            number(value, field + " count", integer=True)
        require(sum(histogram.values()) == count, f"{field}: count mismatch")

    metrics = object_fields(
        data["metrics"], ("success_rate", "requests_per_sec", "latency_ms"), "metrics"
    )
    close(number(metrics["success_rate"], "metrics.success_rate"), 1, "metrics.success_rate")
    close(
        number(metrics["requests_per_sec"], "metrics.requests_per_sec"),
        s["requestsPerSec"],
        "metrics.requests_per_sec",
    )
    latency = object_fields(
        metrics["latency_ms"], ("min", "mean", "p50", "p95", "p99", "max"), "metrics.latency_ms"
    )
    for field, seconds in (
        ("min", s["fastest"]),
        ("mean", s["average"]),
        ("max", s["slowest"]),
        *((p, data["latencyPercentiles"][p]) for p in ("p50", "p95", "p99")),
    ):
        value = number(latency[field], "metrics.latency_ms." + field)
        require(
            abs(value - seconds * 1000) <= 0.0005001,
            f"metrics.latency_ms.{field}: wrong millisecond unit/value",
        )

    rps = object_fields(data["rps"], ("mean", "stddev", "max", "min", "percentiles"), "rps")
    for name in ("mean", "stddev", "max", "min"):
        number(rps[name], "rps." + name)
    for name, value in object_fields(
        rps["percentiles"], percentile_names, "rps.percentiles"
    ).items():
        number(value, "rps.percentiles." + name)
    require(rps["min"] <= rps["mean"] <= rps["max"], "rps: inconsistent range")
    rps_values = [rps["percentiles"][name] for name in percentile_names]
    require(
        rps_values == sorted(rps_values)
        and rps["min"] <= rps_values[0]
        and rps_values[-1] <= rps["max"],
        "rps.percentiles: inconsistent order/range",
    )
    details = object_fields(data["details"], ("DNSDialup", "DNSLookup", "firstByte"), "details")
    for field, triple in details.items():
        object_fields(triple, ("average", "fastest", "slowest"), "details." + field)
        for name, value in triple.items():
            number(value, f"details.{field}.{name}")
        require(
            triple["fastest"] <= triple["average"] <= triple["slowest"],
            f"details.{field}: invalid range",
        )
    return {
        "requests_per_second": s["requestsPerSec"],
        "mean_response_time_ms": number(s["average"] * 1000, "mean milliseconds", positive=True),
        "elapsed_seconds": s["total"],
        "successful_requests": count,
        "response_bytes": s["totalData"],
    }


def validate_run(run: dict) -> None:
    object_fields(
        run,
        (
            "run",
            "requests_per_second",
            "mean_response_time_ms",
            "peak_memory_bytes",
            "memory_samples",
            "elapsed_seconds",
            "successful_requests",
            "response_bytes",
        ),
        "run",
    )
    for field, value in run.items():
        number(
            value,
            field,
            positive=True,
            integer=field
            in (
                "run",
                "peak_memory_bytes",
                "memory_samples",
                "successful_requests",
                "response_bytes",
            ),
        )
    require(run["run"] in (1, 2, 3), "run: expected index 1, 2 or 3")
    require(run["peak_memory_bytes"] <= 536870912, "peak memory exceeds API limit")
    close(
        run["requests_per_second"],
        run["successful_requests"] / run["elapsed_seconds"],
        "run throughput",
    )


def select_run(runs: list[dict]) -> dict:
    require(type(runs) is list and len(runs) == 3, "exactly three measured runs required")
    for run in runs:
        validate_run(run)
    require({run["run"] for run in runs} == {1, 2, 3}, "three distinct run indices required")
    # A whole existing run is selected; never independently median each metric.
    return sorted(runs, key=lambda run: (run["requests_per_second"], run["run"]))[1].copy()


def atomic_json(path: Path, value: dict) -> None:
    """The rename is the commit point; all validation and cleanup precede this."""
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix="." + path.name + ".", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
