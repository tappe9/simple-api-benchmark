"""Run the existing benchmark only from the trusted default-branch Actions workflow."""

import os
import signal
import sys
from pathlib import Path

from .environment import DockerEnvironment, provenance
from .install_oha import ensure_oha
from .process import execute
from .report import REPOSITORY, audit_raw, text, validate_context, validate_report
from .results import BenchmarkFailure, atomic_json, require
from .run import ROOT, load_config, run_benchmark


def trusted_context(environment=None) -> dict:
    environment = os.environ if environment is None else environment
    require(environment.get("GITHUB_ACTIONS") == "true", "official runs require GitHub Actions")
    fields = {
        "repository": "GITHUB_REPOSITORY",
        "ref": "GITHUB_REF",
        "source_commit": "GITHUB_SHA",
        "event": "GITHUB_EVENT_NAME",
        "workflow_ref": "GITHUB_WORKFLOW_REF",
        "workflow_sha": "GITHUB_WORKFLOW_SHA",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
    }
    context = {field: environment.get(variable) for field, variable in fields.items()}
    context["run_url"] = f"https://github.com/{REPOSITORY}/actions/runs/{context['run_id']}"
    validate_context(context)
    return context


def runner_metadata() -> dict:
    variables = {
        "name": "RUNNER_NAME",
        "environment": "RUNNER_ENVIRONMENT",
        "os": "RUNNER_OS",
        "architecture": "RUNNER_ARCH",
        "image_os": "ImageOS",
        "image_version": "ImageVersion",
    }
    result = {
        key: text(os.environ.get(variable), "missing " + variable)
        for key, variable in variables.items()
    }
    require(result["environment"] == "github-hosted", "dedicated runners are outside this baseline")
    cpu = [
        line.partition(":")[2].strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines()
        if line.startswith("model name")
    ]
    result["cpu_model"] = text(cpu[0] if cpu else None, "CPU model unavailable")
    return result


def main() -> int:
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"received signal {signum}")

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        context = trusted_context()
        selected = ROOT / ".cache/official/selected.json"
        require(not selected.exists(), "refusing stale selected artifact")
        oha = ensure_oha()
        metadata = provenance(oha)
        require(
            metadata["source_commit"] == context["source_commit"], "checkout does not match run"
        )
        metadata.update(
            github=context,
            runner=runner_metadata(),
            docker_cli=execute(
                ["docker", "version", "--format", "{{.Client.Version}}"], timeout=15
            ).strip(),
            docker_compose=execute(["docker", "compose", "version", "--short"], timeout=15).strip(),
        )
        environment = DockerEnvironment(oha, ROOT / ".cache/official/raw")
        metadata["artifact_directory"] = str(environment.artifacts.relative_to(ROOT))
        report = run_benchmark(
            environment, load_config(), selected.with_name("candidate.json"), metadata=metadata
        )
        report.update(mode="official", official=True)
        validate_report(report, expected_context=context)
        audit_raw(report, ROOT)
        atomic_json(selected, report)
        print("All 36 measurements and cleanup passed; official artifact is ready for publication.")
        return 0
    except (BenchmarkFailure, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Official benchmark failed: {error}", file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
