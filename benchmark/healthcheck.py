"""Health-policy support for the non-publishing benchmark investigation."""

import math
import shlex
import time

from .contract_test import ContractFailure, assert_response, load_cases, read_response
from .registry import implementation
from .results import BenchmarkFailure, require, strict_json

CONTAINER_HEALTHCHECK = "container-healthcheck"
EXTERNAL_READINESS = "external-readiness"
_POLICIES = (CONTAINER_HEALTHCHECK, EXTERNAL_READINESS)
_EXEC_PREFIXES = ("exec_create", "exec_start", "exec_die")


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


def _validate_window(started: int | None, completed: int | None) -> bool:
    bounded = started is not None or completed is not None
    if not bounded:
        return False
    require(
        type(started) is int
        and not isinstance(started, bool)
        and started > 0
        and type(completed) is int
        and not isinstance(completed, bool)
        and completed >= started,
        "invalid exact Docker event audit window",
    )
    return True


def parse_exec_events(
    raw: bytes,
    *,
    container_id: str,
    probe_command: list[str] | None,
    max_events: int = 128,
    window_started_ns: int | None = None,
    window_completed_ns: int | None = None,
) -> dict:
    """Parse Docker exec events and attribute activity to the exact audit interval.

    Without explicit interval bounds this retains the original strict fixture contract:
    every observed execution must contain create/start/die. With bounds, callers may
    query a padded history window. Complete executions before the exact interval are
    ignored, executions overlapping the left boundary are counted, and an execution
    started before the right boundary may legitimately have its die event outside the
    query window.
    """
    require(
        type(container_id) is str and len(container_id) == 64,
        "invalid API container ID for event audit",
    )
    require(
        type(max_events) is int and not isinstance(max_events, bool) and max_events > 0,
        "invalid event limit",
    )
    require(type(raw) is bytes, "Docker event payload must be bytes")
    bounded = _validate_window(window_started_ns, window_completed_ns)
    lines = [line for line in raw.splitlines() if line]
    require(len(lines) <= max_events, "Docker event window exceeds audit limit")
    expected_probe = shlex.join(probe_command) if probe_command is not None else None
    executions: dict[str, dict] = {}
    for line in lines:
        value = strict_json(line)
        require(
            type(value) is dict and value.get("Type") == "container",
            "unexpected Docker event type",
        )
        actor = value.get("Actor")
        require(
            type(actor) is dict and actor.get("ID") == container_id,
            "Docker event belongs to wrong container",
        )
        attributes = actor.get("Attributes")
        require(type(attributes) is dict, "Docker exec event attributes missing")
        exec_id = attributes.get("execID")
        require(
            type(exec_id) is str and len(exec_id) == 64,
            "Docker exec ID missing or invalid",
        )
        action = value.get("Action")
        timestamp = value.get("timeNano")
        require(
            type(action) is str
            and type(timestamp) is int
            and not isinstance(timestamp, bool)
            and timestamp > 0,
            "invalid Docker exec event",
        )
        prefix, separator, command = action.partition(": ")
        require(prefix in _EXEC_PREFIXES, "unexpected Docker exec action")
        if prefix in ("exec_create", "exec_start"):
            require(separator == ": " and bool(command), "Docker exec command missing")
        record = executions.setdefault(exec_id, {"command": None, "events": {}})
        require(prefix not in record["events"], "duplicate Docker exec lifecycle event")
        record["events"][prefix] = timestamp
        if command:
            if record["command"] is None:
                record["command"] = command
            else:
                require(
                    record["command"] == command,
                    "Docker exec command changed within lifecycle",
                )

    probe_starts = []
    non_probe = 0
    attributed = 0
    for record in executions.values():
        events = record["events"]
        if not bounded:
            require(
                set(events) == set(_EXEC_PREFIXES),
                "incomplete Docker exec lifecycle in audit window",
            )
        create = events.get("exec_create")
        start = events.get("exec_start")
        die = events.get("exec_die")
        if create is not None and start is not None:
            require(create <= start, "Docker exec create/start order is invalid")
        if start is not None and die is not None:
            require(start <= die, "Docker exec start/die order is invalid")
        if create is not None and die is not None:
            require(create <= die, "Docker exec create/die order is invalid")

        if bounded:
            if start is None:
                if die is not None and die >= window_started_ns:
                    raise BenchmarkFailure("cannot attribute exec overlapping left audit boundary")
                continue
            overlaps = start <= window_completed_ns and (die is None or die >= window_started_ns)
            if not overlaps:
                continue
        require(record["command"] is not None, "Docker exec lifecycle has no command")
        attributed += 1
        if expected_probe is not None and record["command"] == expected_probe:
            probe_starts.append(start)
        else:
            non_probe += 1

    probe_starts.sort()
    return {
        "total_execs": attributed,
        "probe_execs": len(probe_starts),
        "non_probe_execs": non_probe,
        "probe_start_timestamps_ns": probe_starts,
    }


def require_probe_only_activity(summary: dict) -> None:
    """Require recurring probe activity and reject unrelated execs in baseline mode."""
    require(type(summary) is dict, "health event summary missing")
    require(summary.get("probe_execs", 0) > 0, "no API health probe activity observed")
    require(summary.get("non_probe_execs") == 0, "unexpected non-health exec activity observed")
    require(
        summary.get("total_execs") == summary.get("probe_execs"),
        "inconsistent health event summary",
    )


def require_no_exec_activity(summary: dict) -> None:
    """Controlled mode must not execute any command inside the measured API container."""
    require(
        type(summary) is dict and summary.get("total_execs") == 0,
        "unexpected API exec activity observed",
    )
