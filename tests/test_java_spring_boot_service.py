"""Verify the locked host build and the real Java/PostgreSQL production container."""

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.contract_test import Case, assert_response, load_cases, read_response
from benchmark.environment import validate_processes, validate_state
from benchmark.java_versions import DEPENDENCY_FILES, pinned_versions

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/java-spring-boot"
SERVICE = "java-spring-boot"
BASE_URL = "http://127.0.0.1:8080"
SESSION_COUNT = "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'simple-api-java';"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, *, timeout=60, cwd=ROOT):
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command[0]}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


def count_value(value):
    require(
        type(value) is str and re.fullmatch(r"[0-9]+\s*", value) is not None,
        "invalid database session count",
    )
    return int(value)


def validate_pool_count(value):
    require(0 <= count_value(value) <= 10, "Java connection pool exceeded ten sessions")


def stopped_state(container):
    try:
        state = container["State"]
        require(
            all(state[key] is False for key in ("Running", "Restarting", "Dead", "OOMKilled")),
            "container is not safely stopped",
        )
        require(state["Status"] == "exited", "container did not exit")
        require(type(state["ExitCode"]) is int, "missing integer exit status")
        require(
            type(container["RestartCount"]) is int and container["RestartCount"] == 0,
            "container restarted",
        )
        return state
    except (KeyError, TypeError) as error:
        raise RuntimeError("incomplete stopped-container evidence") from error


def validate_shutdown(container, remaining):
    require(stopped_state(container)["ExitCode"] in (0, 143), "JVM did not exit gracefully")
    require(count_value(remaining) == 0, "JVM left database sessions open")


def validate_failed_startup(container, logs):
    require(
        stopped_state(container)["ExitCode"] == 1, "expected an actual application startup failure"
    )
    require(
        type(logs) is str and "application startup failed" in logs,
        "missing application failure evidence",
    )
    lowered = logs.lower()
    require(
        not any(
            value in lowered for value in ("password", "secret-67", "jdbc:", "select ", "at org.")
        ),
        "startup log disclosed internal details",
    )


def dependency_hashes():
    return {
        name: hashlib.sha256((APP / name).read_bytes()).hexdigest() for name in DEPENDENCY_FILES
    }


def validate_distribution_pins(dockerfile):
    """Require checksum-verified, architecture-specific BuildKit downloads."""
    require(
        "FROM archives-${TARGETARCH} AS archives\n" in dockerfile,
        "Java archive selection must follow the target architecture",
    )
    for platform, architecture in (("amd64", "x64"), ("arm64", "aarch64")):
        blocks = re.findall(
            rf"(?ms)^FROM scratch AS archives-{platform}\n(.*?)(?=^FROM )", dockerfile
        )
        require(len(blocks) == 1, "missing or duplicate Java distribution platform")
        entries = re.findall(
            r"(?m)^ADD --checksum=sha256:([0-9a-f]{64}) "
            r"https://github\.com/adoptium/temurin25-binaries/releases/download/"
            r"jdk-25\.0\.4\.1%2B1/OpenJDK25U-(jdk|jre)_"
            r"(x64|aarch64)_linux_hotspot_25\.0\.4\.1_1\.tar\.gz /tmp/(jdk|jre)\.tar\.gz$",
            blocks[0],
        )
        require(
            len(entries) == 2
            and [(kind, arch, destination) for _, kind, arch, destination in entries]
            == [("jdk", architecture, "jdk"), ("jre", architecture, "jre")],
            "Java distribution archives must have complete SHA-256 pins and correct platforms",
        )
        require(
            len(re.findall(r"(?m)^ADD ", blocks[0])) == 2, "unexpected Java distribution download"
        )


def static_checks():
    versions = pinned_versions(APP)
    require(versions["java"] == "25.0.4.1+1", "unexpected JDK build")
    require(versions["spring-boot"] == "4.1.1", "unexpected Spring Boot version")
    dockerfile = (APP / "Dockerfile").read_text()
    validate_distribution_pins(dockerfile)
    images = re.findall(r"^FROM (\S+)", dockerfile, re.MULTILINE)
    require(
        len(images) == 5
        and images[:3] == ["scratch", "scratch", "archives-${TARGETARCH}"]
        and all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in images[3:]),
        "Docker bases must be digest pinned",
    )
    require("USER 10001:10001" in dockerfile, "Java production image must run non-root")
    source = APP / "src/main/java/dev/simpleapibenchmark"
    fibonacci = (source / "Fibonacci.java").read_text()
    require(
        "calculate(n - 1) + calculate(n - 2)" in fibonacci,
        "CPU workload must remain direct recursion",
    )
    require(
        "Fibonacci.calculate(30)" in (source / "ApiController.java").read_text(),
        "CPU calculation must occur per request",
    )
    print("Java static versions:", json.dumps(versions, sort_keys=True))


def host_checks():
    before = dependency_hashes()
    output = run([str(APP / "gradlew"), "--no-daemon", "test", "installDist"], cwd=APP, timeout=900)
    print(output)
    require(dependency_hashes() == before, "validation changed committed dependency evidence")
    libraries = {path.name for path in (APP / "build/install/java-spring-boot/lib").glob("*.jar")}
    versions = pinned_versions(APP)
    for name, version in (
        ("spring-boot", versions["spring-boot"]),
        ("tomcat-embed-core", versions["tomcat"]),
        ("postgresql", versions["postgresql"]),
        ("HikariCP", versions["hikaricp"]),
        ("jackson-databind", versions["jackson"]),
    ):
        require(
            f"{name}-{version}.jar" in libraries,
            "runtime distribution does not match locked metadata",
        )
    require(
        not any(name.startswith(("junit-", "mockito-", "spring-test-")) for name in libraries),
        "test dependencies entered the production distribution",
    )


def container_checks():
    project = "sab-java-acceptance-" + uuid.uuid4().hex[:12]
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "docker-compose.yml")]

    def dc(*args, timeout=60):
        return run([*compose, *args], timeout=timeout)

    def inspect(identifier):
        return json.loads(run(["docker", "inspect", identifier]))[0]

    def sql(statement):
        return dc(
            "exec",
            "-T",
            "postgres",
            "psql",
            "--username",
            "benchmark",
            "--dbname",
            "benchmark",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            "--command",
            statement,
        ).strip()

    def response(case):
        assert_response(case, read_response(BASE_URL, case.path, timeout=10), SERVICE)

    def wait_stopped(identifier, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = inspect(identifier)
            if state["State"]["Running"] is False:
                return state
            time.sleep(0.2)
        raise RuntimeError("Java container did not stop within its deadline")

    failure = None
    try:
        dc("build", SERVICE, timeout=900)
        dc("up", "-d", "--wait", "--wait-timeout", "90", SERVICE, timeout=150)
        identifier = dc("ps", "-q", SERVICE).strip()
        require(
            re.fullmatch(r"[0-9a-f]{64}", identifier) is not None,
            "missing full Java container identity",
        )
        state = inspect(identifier)
        identity = validate_state(state, project, SERVICE)
        require(state["Config"]["User"] == "10001:10001", "Java image is not non-root")
        require("ALL" in state["HostConfig"]["CapDrop"], "Linux capabilities were not dropped")
        require(
            any(
                value.startswith("no-new-privileges")
                for value in state["HostConfig"]["SecurityOpt"]
            ),
            "no-new-privileges is missing",
        )
        ports = state["HostConfig"]["PortBindings"]
        require(
            ports == {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
            "unexpected Java host ports",
        )
        require(
            set(state["NetworkSettings"]["Networks"]) == {project + "_benchmark"},
            "Java escaped its owned benchmark network",
        )
        database = inspect(dc("ps", "-q", "postgres").strip())
        require(
            not database["HostConfig"]["PortBindings"], "PostgreSQL must not publish a host port"
        )
        validate_processes(state, run(["docker", "top", identifier, "-eo", "pid,args"]))
        runtime = run(
            ["docker", "exec", identifier, "java", "-XshowSettings:properties", "-version"]
        )
        # Java emits settings on stderr; query its release manifest independently.
        release = run(["docker", "exec", identifier, "cat", "/opt/java/openjdk/release"])
        require('JAVA_RUNTIME_VERSION="25.0.4.1+1' in release, "production JRE and host JDK differ")
        require(runtime == "", "unexpected Java version stdout")
        for case in load_cases():
            response(case)
        for value in (-(2**63), 2**63 - 1, 9007199254740993, 0):
            sql(f"INSERT INTO items (id,name,price) VALUES ({value},'Boundary',7);")
            response(Case(f"/db/{value}", 200, {"id": value, "name": "Boundary", "price": 7}))
        for value in ("9223372036854775808", "-9223372036854775809", "42junk", "1.5"):
            response(Case("/db/" + value, 400, {"error": "invalid id"}))
        sql("UPDATE items SET name='Live update', price=73 WHERE id=42;")
        live = Case("/db/42", 200, {"id": 42, "name": "Live update", "price": 73})
        response(live)
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
            futures = [executor.submit(response, live) for _ in range(96)]
            while any(not future.done() for future in futures):
                validate_pool_count(sql(SESSION_COUNT))
                time.sleep(0.02)
            for future in futures:
                future.result()
        validate_pool_count(sql(SESSION_COUNT))
        validate_state(inspect(identifier), project, SERVICE, identity)
        validate_processes(
            inspect(identifier), run(["docker", "top", identifier, "-eo", "pid,args"])
        )
        sql("ALTER TABLE items RENAME TO unavailable_items;")
        response(Case("/db/42", 500, {"error": "internal server error"}))
        sql("ALTER TABLE unavailable_items RENAME TO items;")
        response(live)
        started = time.monotonic()
        run(["docker", "kill", "--signal", "TERM", identifier])
        stopped = wait_stopped(identifier, 15)
        require(time.monotonic() - started < 15, "graceful JVM shutdown exceeded its deadline")
        validate_shutdown(stopped, sql(SESSION_COUNT))
        for index, override in enumerate(
            ("DATABASE_PASSWORD=secret-67", "DATABASE_HOST=127.0.0.1", "DATABASE_PORT=65536")
        ):
            name = f"{project}-failure-{index}"
            dc(
                "run",
                "--detach",
                "--no-deps",
                "--name",
                name,
                "--env",
                override,
                SERVICE,
                timeout=30,
            )
            failed = wait_stopped(name, 30)
            logs = run(["docker", "logs", name])
            # Application stderr is returned separately by Docker; capture both streams.
            result = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True, timeout=10, check=True
            )
            validate_failed_startup(failed, logs + result.stderr)
            require(sql(SESSION_COUNT) == "0", "failed startup left database sessions open")
        print(
            "Java production acceptance: live SQL, BIGINT, pool, limits, process isolation, failures and shutdown passed"
        )
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            dc("down", "--remove-orphans", "--volumes", "--timeout", "10", timeout=90)
            label = "label=com.docker.compose.project=" + project
            require(
                not run(["docker", "ps", "-aq", "--filter", label]).strip(),
                "owned acceptance containers remain",
            )
            require(
                not run(["docker", "network", "ls", "-q", "--filter", label]).strip(),
                "owned acceptance networks remain",
            )
        except Exception as cleanup:
            if failure is not None:
                raise RuntimeError(
                    f"Java acceptance and owned cleanup both failed: {failure}; {cleanup}"
                ) from failure
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    static_checks()
    if not args.static:
        host_checks()
        container_checks()


if __name__ == "__main__":
    main()
