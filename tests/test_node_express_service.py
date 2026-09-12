#!/usr/bin/env python3
"""Focused source and real-container acceptance for Node.js / Express."""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "node-express"
IMAGE = "node:24.20.0-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e"
DEPENDENCIES = {"express": "5.2.1", "pg": "8.23.0"}
DB_ENVIRONMENT = {"DATABASE_HOST":"postgres","DATABASE_PORT":"5432","DATABASE_NAME":"benchmark","DATABASE_USER":"benchmark","DATABASE_PASSWORD":"benchmark"}

class CheckFailure(RuntimeError): pass

def require(condition, message):
    if not condition: raise CheckFailure(message)

def run(command, *, cwd=ROOT, timeout=600, check=True):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check: require(result.returncode == 0, f"command failed: {' '.join(command)}\n{result.stderr}")
    return result

def check_static_contract():
    for name in ("package.json","package-lock.json","Dockerfile",".node-version","src/app.js","src/database.js","src/server.js","src/healthcheck.js","test/app.test.js","test/database.test.js","test/server.test.js","test/healthcheck.test.js"):
        require((APP / name).is_file(), f"required file missing: {name}")
    package = json.loads((APP / "package.json").read_text())
    lock = json.loads((APP / "package-lock.json").read_text())
    require(package["dependencies"] == DEPENDENCIES, "dependencies are not exactly pinned")
    require(lock["packages"][""]["dependencies"] == DEPENDENCIES, "lock root differs")
    for name, version in DEPENDENCIES.items():
        require(lock["packages"][f"node_modules/{name}"]["version"] == version, f"unlocked {name}")
    require(all(not key or bool(value.get("integrity")) for key, value in lock["packages"].items()), "lock integrity missing")
    dockerfile = (APP / "Dockerfile").read_text()
    require(dockerfile.count(f"FROM {IMAGE}") == 2, "Node image not pinned")
    require("USER node" in dockerfile and "npm ci --omit=dev --ignore-scripts" in dockerfile, "Docker production constraints missing")
    source = (APP / "src/app.js").read_text()
    compact = re.sub(r"\s+", "", source)
    require("WHERE id = $1" in source, "bound SQL missing")
    require("returnfibonacci(n-1)+fibonacci(n-2)" in compact, "direct recursion missing")
    require("result:fibonacci(30)" in compact, "Fibonacci(30) missing")
    database = (APP / "src/database.js").read_text()
    require(re.search(r"max:\s*10\b", database), "pool max 10 missing")

def check_configuration(config):
    service = config["services"]["node-express"]
    require(Path(service["build"]["context"]).resolve() == APP, "wrong build context")
    require(service["environment"] == {**DB_ENVIRONMENT,"NODE_ENV":"production"}, "wrong environment")
    require(float(service["cpus"]) == 1 and str(service["mem_limit"]) == "536870912", "wrong resource limits")
    require(service["restart"] == "no", "restart must be disabled")
    port = service["ports"][0]
    require(port["host_ip"] == "127.0.0.1" and str(port["published"]) == "8080", "port must be loopback-only")
    require(service["healthcheck"]["test"] == ["CMD","node","src/healthcheck.js"], "wrong healthcheck")

def request_json(path, status, expected):
    try: response = urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=5)
    except urllib.error.HTTPError as error: response = error
    with response:
        require(response.status == status, f"{path}: status {response.status}")
        require(response.headers.get_content_type() == "application/json", f"{path}: not JSON")
        payload = json.load(response)
    require(payload == expected, f"{path}: {payload!r}")

def sql(statement):
    return run(["docker","compose","exec","-T","postgres","psql","-X","-U","benchmark","-d","benchmark","-v","ON_ERROR_STOP=1","-Atc",statement]).stdout.strip()

def check_running_service():
    container = run(["docker","compose","ps","--quiet","node-express"]).stdout.strip()
    require(container, "Express container missing")
    state = json.loads(run(["docker","inspect",container]).stdout)[0]
    require(state["State"]["Health"]["Status"] == "healthy", "Express unhealthy")
    require(state["RestartCount"] == 0, "Express restarted")
    require(state["HostConfig"]["NanoCpus"] == 1000000000 and state["HostConfig"]["Memory"] == 536870912, "runtime limits differ")
    require(state["Config"]["User"] == "node", "runtime not non-root node user")
    require(state["Path"] == "node" and state["Args"] == ["src/server.js"], "server wrapper detected")
    require(not state["HostConfig"]["Privileged"] and state["HostConfig"]["CapDrop"] == ["ALL"], "container privilege differs")
    processes = run(["docker","top",container,"-eo","pid,args"]).stdout.splitlines()[1:]
    commands = [row.split(maxsplit=1)[1] for row in processes if row.strip()]
    require(commands.count("node src/server.js") == 1, "expected one Node server")
    return container

def check_endpoints():
    request_json("/health",200,{"status":"ok"})
    request_json("/json",200,{"message":"Hello, World!","items":[1,2,3,4,5]})
    request_json("/db/42",200,{"id":42,"name":"Item 42","price":4200})
    request_json("/db/999",404,{"error":"not found"})
    for value in ("invalid","42junk","1.0","9223372036854775808"):
        request_json(f"/db/{value}",400,{"error":"invalid id"})
    request_json("/cpu",200,{"input":30,"result":832040})
    sql("UPDATE items SET name = 'Updated Item', price = 7 WHERE id = 42;")
    request_json("/db/42",200,{"id":42,"name":"Updated Item","price":7})
    for value in (9007199254740993,9223372036854775807,-9223372036854775808):
        sql(f"INSERT INTO items VALUES ({value}, 'Boundary item', 1);")
        request_json(f"/db/{value}",200,{"id":value,"name":"Boundary item","price":1})
    sql("DROP TABLE items;")
    request_json("/db/42",500,{"error":"internal server error"})

def check_dynamic_contract():
    project = None
    try:
        run(["npm","ci"], cwd=APP)
        run(["npm","test"], cwd=APP)
        run(["npm","run","lint"], cwd=APP)
        config = json.loads(run(["docker","compose","config","--format","json"]).stdout)
        project = config["name"]
        check_configuration(config)
        run(["docker","compose","up","--detach","--build","--wait","--wait-timeout","180","node-express"])
        container = check_running_service()
        check_endpoints()
        run(["docker","compose","stop","--timeout","10","node-express"])
        stopped = json.loads(run(["docker","inspect",container]).stdout)[0]
        require(stopped["State"]["ExitCode"] == 0, "Express did not shut down cleanly")
        require(sql("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();") == "0", "DB connections remain")
    finally:
        cleanup = run(["make","down"], check=False)
        require(cleanup.returncode == 0, "cleanup failed")
        remaining = run(["docker","compose","ps","-a","--quiet"], check=False)
        require(remaining.returncode == 0 and not remaining.stdout.strip(), "containers remain")
        if project:
            networks = run(["docker","network","ls","--quiet","--filter",f"label=com.docker.compose.project={project}"], check=False)
            require(networks.returncode == 0 and not networks.stdout.strip(), "network remains")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    try:
        check_static_contract()
        if not args.static: check_dynamic_contract()
    except (CheckFailure, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f"Node / Express acceptance failed: {error}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__": raise SystemExit(main())
