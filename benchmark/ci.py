"""CI support helpers for registry-derived planning and aggregate checks."""

import argparse
import json
import os
import sys

from . import registry

_REQUIRED_RESULTS = ("plan", "shared", "implementation", "smoke")
_ENV_RESULTS = {
    "plan": "PLAN_RESULT",
    "shared": "SHARED_RESULT",
    "implementation": "IMPLEMENTATION_RESULT",
    "smoke": "SMOKE_RESULT",
}


def matrix_payload() -> dict[str, list[str]]:
    """Return the active implementation matrix in authoritative registry order."""
    return {"implementation": list(registry.implementation_ids())}


def require_success(results: dict[str, str]) -> None:
    """Reject missing, extra, failed, cancelled, or skipped required CI results."""
    if set(results) != set(_REQUIRED_RESULTS):
        raise RuntimeError("required CI result set is incomplete")
    invalid = [name for name in _REQUIRED_RESULTS if results[name] != "success"]
    if invalid:
        details = ", ".join(f"{name}={results[name]!r}" for name in invalid)
        raise RuntimeError("required CI jobs did not all succeed: " + details)


def _environment_results() -> dict[str, str]:
    return {name: os.environ.get(variable, "") for name, variable in _ENV_RESULTS.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "require-success"))
    args = parser.parse_args(argv)
    try:
        if args.command == "matrix":
            payload = json.dumps(matrix_payload(), ensure_ascii=True, separators=(",", ":"))
            print("matrix=" + payload)
        else:
            require_success(_environment_results())
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print(f"CI validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
