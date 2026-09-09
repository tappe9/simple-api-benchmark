"""Health-policy support for the non-publishing benchmark investigation."""

import math
import time

from .contract_test import ContractFailure, assert_response, load_cases, read_response
from .registry import implementation
from .results import BenchmarkFailure, require

CONTAINER_HEALTHCHECK = "container-healthcheck"
EXTERNAL_READINESS = "external-readiness"
_POLICIES = (CONTAINER_HEALTHCHECK, EXTERNAL_READINESS)


def validate_policy(value: str) -> str:
    """Accept only explicit benchmark API health-policy names."""
    require(type(value) is str and value in _POLICIES, "unsupported API health policy")
    return value


def override_text(implementation_id: str) -> str:
    """Disable only one registered API healthcheck in a Compose override."""
    implementation(implementation_id)
    return f"services:\n  {implementation_id}:\n    healthcheck:\n      disable: true\n"


def wait_external_readiness(
    base_url: str,
    implementation_id: str,
    check_state,
    *,
    timeout_seconds: float = 60.0,
    request_timeout: float = 2.0,
    clock=time.monotonic,
    sleep=time.sleep,
    reader=read_response,
) -> dict:
    """Wait for the documented health response without polling during measurement."""
    implementation(implementation_id)
    require(
        type(timeout_seconds) in (int, float)
        and not isinstance(timeout_seconds, bool)
        and math.isfinite(timeout_seconds)
        and timeout_seconds > 0,
        "readiness timeout must be positive and finite",
    )
    require(
        type(request_timeout) in (int, float)
        and not isinstance(request_timeout, bool)
        and math.isfinite(request_timeout)
        and request_timeout > 0,
        "readiness request timeout must be positive and finite",
    )
    health_cases = [case for case in load_cases() if case.path == "/health"]
    require(len(health_cases) == 1, "shared contract must define exactly one health case")
    case = health_cases[0]
    started = clock()
    deadline = started + timeout_seconds
    attempts = 0
    while True:
        now = clock()
        if now >= deadline:
            raise BenchmarkFailure("external readiness deadline exceeded")
        check_state()
        attempts += 1
        remaining = deadline - now
        try:
            response = reader(
                base_url,
                case.path,
                timeout=min(float(request_timeout), remaining),
            )
        except ContractFailure as error:
            if not str(error).startswith("transport:"):
                raise
            now = clock()
            remaining = deadline - now
            if remaining <= 0:
                raise BenchmarkFailure("external readiness deadline exceeded") from error
            interval = min(0.25, remaining)
            sleep(interval)
            if clock() >= deadline:
                raise BenchmarkFailure("external readiness deadline exceeded") from error
            continue
        assert_response(case, response, implementation_id)
        check_state()
        return {
            "attempts": attempts,
            "duration_seconds": clock() - started,
        }
