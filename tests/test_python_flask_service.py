"""Focused unit and real-container acceptance for Python / Flask."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "python-flask"
SERVICE = "python-flask"


class CheckFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def run(
    command: list[str], *, cwd: Path = ROOT, timeout: int = 600, check: bool = True
):
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    if check:
        require(
            result.returncode == 0,
            f"command failed ({result.returncode}): {' '.join(command)}",
        )
    return result


def request_json(path: str, status: int, expected: dict) -> None:
    try:
        response = urllib.request.urlopen(f"http://127.0.0.1:8080{path}", timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        require(response.status == status, f"{path}: status {response.status}")
        require(
            response.headers.get_content_type() == "application/json",
            f"{path}: not JSON",
        )
        payload = json.load(response)
    require(payload == expected, f"{path}: unexpected response {payload!r}")
    for key, value in expected.items():
        require(type(payload[key]) is type(value), f"{path}: wrong JSON type for {key}")


def sql(statement: str) -> str:
    return run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-U",
            "benchmark",
            "-d",
            "benchmark",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            statement,
        ]
    ).stdout.strip()


def focused_tests() -> None:
    require(sys.version_info[:3] == (3, 14, 7), "acceptance requires Python 3.14.7")
    with tempfile.TemporaryDirectory(prefix="python-flask-tests-") as directory:
        run([sys.executable, "-m", "venv", directory])
        python = str(Path(directory) / "bin" / "python")
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "-r",
                "requirements-dev.lock",
            ],
            cwd=APP,
        )
        run([python, "-m", "pip", "check"], cwd=APP)
        run([python, "-m", "ruff", "check", "."], cwd=APP)
        run([python, "-m", "pytest", "-q"], cwd=APP)


def running_service() -> str:
    container = run(["docker", "compose", "ps", "--quiet", SERVICE]).stdout.strip()
    require(bool(container), "Flask container missing")
    state = json.loads(run(["docker", "inspect", container]).stdout)[0]
    require(
        state["State"]["Health"]["Status"] == "healthy", "Flask container unhealthy"
    )
    require(state["RestartCount"] == 0, "Flask container restarted")
    require(state["HostConfig"]["NanoCpus"] == 1_000_000_000, "CPU limit differs")
    require(state["HostConfig"]["Memory"] == 536_870_912, "memory limit differs")
    require(state["Config"]["User"] == "10001:10001", "runtime user differs")
    require(
        state["Path"] == "python" and state["Args"] == ["-m", "benchmark_api.server"],
        "unexpected server wrapper",
    )
    require(state["HostConfig"]["CapDrop"] == ["ALL"], "capabilities not dropped")
    require(
        "no-new-privileges:true" in state["HostConfig"]["SecurityOpt"],
        "privilege escalation allowed",
    )
    processes = run(
        ["docker", "top", container, "-eo", "pid,args"]
    ).stdout.splitlines()[1:]
    commands = [line.split(maxsplit=1)[1] for line in processes if line.strip()]
    servers = [command for command in commands if "benchmark_api.server" in command]
    require(len(servers) == 1, f"expected one Waitress server process, got {servers!r}")
    return container


def endpoints() -> None:
    request_json("/health", 200, {"status": "ok"})
    request_json("/json", 200, {"message": "Hello, World!", "items": [1, 2, 3, 4, 5]})
    for value in ("42", "+42", "00042"):
        request_json(f"/db/{value}", 200, {"id": 42, "name": "Item 42", "price": 4200})
    request_json("/db/999", 404, {"error": "not found"})
    for value in (
        "invalid",
        "42junk",
        "1.0",
        "1e2",
        "0x2a",
        "1_000",
        "9223372036854775808",
        "-9223372036854775809",
    ):
        request_json(f"/db/{value}", 400, {"error": "invalid id"})
    for _ in range(2):
        request_json("/cpu", 200, {"input": 30, "result": 832040})
    sql("UPDATE items SET name = 'Updated Item', price = 7 WHERE id = 42;")
    request_json("/db/42", 200, {"id": 42, "name": "Updated Item", "price": 7})
    for value in (9007199254740993, 9223372036854775807, -9223372036854775808):
        sql(f"INSERT INTO items VALUES ({value}, 'Boundary item', 1);")
        request_json(
            f"/db/{value}", 200, {"id": value, "name": "Boundary item", "price": 1}
        )
    sql("DROP TABLE items;")
    request_json("/db/42", 500, {"error": "internal server error"})


def startup_failure() -> None:
    result = run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "DATABASE_HOST=missing.invalid",
            SERVICE,
        ],
        timeout=45,
        check=False,
    )
    require(result.returncode != 0, "service started without a reachable database")
    require(
        "password" not in (result.stdout + result.stderr).lower(),
        "startup failure leaked credentials",
    )


def graceful_shutdown(container: str) -> None:
    run(["docker", "kill", "--signal=TERM", container])
    result = run(["docker", "wait", container], timeout=30)
    require(
        result.stdout.strip() == "0", f"SIGTERM exit code was {result.stdout.strip()!r}"
    )


def main() -> int:
    try:
        focused_tests()
        run(["docker", "compose", "build", SERVICE], timeout=900)
        startup_failure()
        run(
            [
                "docker",
                "compose",
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                "60",
                SERVICE,
            ],
            timeout=180,
        )
        container = running_service()
        endpoints()
        graceful_shutdown(container)
        print("Python / Flask real-container acceptance passed.")
        return 0
    except (CheckFailure, subprocess.TimeoutExpired) as error:
        print(f"Flask acceptance failed: {error}", file=sys.stderr)
        return 1
    finally:
        run(
            ["docker", "compose", "down", "--remove-orphans", "--volumes"],
            timeout=120,
            check=False,
        )


if __name__ == "__main__":
    raise SystemExit(main())
