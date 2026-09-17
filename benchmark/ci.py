"""CI support helpers for registry-derived planning and aggregate checks."""

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from . import registry

# Display languages are registry data, not implementation-ID prefixes.
_LANGUAGE_TOOLCHAINS = {
    "Go": "go",
    "Rust": "rust",
    "Node.js": "node",
    "Python": "python",
    "Java": "java",
}
_TOOLCHAIN_COMMANDS = {
    "go": ("go", "gofmt"),
    "rust": (
        "rustup",
        "rustc",
        "rustdoc",
        "cargo",
        "rustfmt",
        "cargo-fmt",
        "cargo-clippy",
        "clippy-driver",
    ),
    "node": ("node", "nodejs", "npm", "npx", "corepack"),
    "java": ("java", "javac", "jar", "javadoc", "gradle"),
    "python": (),  # Python is the common harness and must remain available to every job.
}

_REQUIRED_RESULTS = ("plan", "shared", "implementation", "smoke")
_ENV_RESULTS = {
    "plan": "PLAN_RESULT",
    "shared": "SHARED_RESULT",
    "implementation": "IMPLEMENTATION_RESULT",
    "smoke": "SMOKE_RESULT",
}


def toolchain_for(identifier: str) -> str:
    """Resolve a registered implementation to an explicitly supported host toolchain."""
    language = registry.implementation(identifier)["language"]
    if not isinstance(language, str) or language not in _LANGUAGE_TOOLCHAINS:
        raise RuntimeError(f"unsupported CI language: {language!r}")
    return _LANGUAGE_TOOLCHAINS[language]


def matrix_payload() -> dict[str, list[dict[str, str]]]:
    """Plan all registered implementations, including inactive cohort members."""
    registry.validate_registry(registry.REGISTRY)
    return {
        "include": [
            {"implementation": identifier, "toolchain": toolchain_for(identifier)}
            for identifier in registry.implementation_ids()
        ]
    }


def run_isolated(identifier: str, command: list[str]) -> int:
    """Reject incidental host-toolchain use during a CI gate, without changing local Make.

    PATH guards are dependency checks, not a security sandbox. Docker builders and
    Actions' own runtimes remain unaffected. A version-only rustc probe reports
    absence; actual tool use is fatal even when the child ignores its failure.
    """
    toolchain = toolchain_for(identifier)
    if not command:
        raise RuntimeError("an isolated CI command is required")
    with tempfile.TemporaryDirectory(prefix="sab-ci-toolchains-") as directory:
        root = Path(directory)
        marker = root / "invoked"
        for group, names in _TOOLCHAIN_COMMANDS.items():
            if group == toolchain:
                continue
            for name in names:
                guard = root / name
                # pip probes rustc for its User-Agent, even for binary-only installs.
                # Report absence without executing a host compiler or inventing a version.
                optional_probe = (
                    'if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then exit 127; fi\n'
                    if name == "rustc"
                    else ""
                )
                guard.write_text(
                    "#!/bin/sh\n"
                    + optional_probe
                    + f"printf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(marker))}\n"
                    f"printf '%s\\n' 'undeclared host toolchain: {name}' >&2\n"
                    "exit 127\n",
                    encoding="utf-8",
                )
                guard.chmod(0o700)
        environment = dict(os.environ)
        environment["PATH"] = directory + os.pathsep + environment.get("PATH", os.defpath)
        result = subprocess.run(command, env=environment, check=False)
        if marker.exists():
            invoked = ", ".join(sorted(set(marker.read_text(encoding="utf-8").splitlines())))
            raise RuntimeError("undeclared host toolchain invoked: " + invoked)
        return result.returncode


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
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("matrix")
    commands.add_parser("require-success")
    isolated = commands.add_parser("run-isolated")
    isolated.add_argument("--implementation", required=True)
    isolated.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "run-isolated":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return run_isolated(args.implementation, command)
        if args.action == "matrix":
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
