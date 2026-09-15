"""Isolated synthetic cohort fixtures; never an official measurement input."""

import copy
import json
from pathlib import Path

from benchmark.healthcheck import CONTAINER_HEALTHCHECK

ROOT = Path(__file__).resolve().parents[1]


def extended_registry():
    from benchmark.registry import load_registry

    registry = copy.deepcopy(load_registry())
    extension = json.loads((ROOT / "tests/fixtures/registry/extended.json").read_text())
    registry["implementations"].extend(extension["implementations"])
    registry["cohorts"][extension["cohort_id"]] = {
        "definition": "simple-api-v1",
        "members": extension["members"],
    }
    registry["active_cohort"] = extension["cohort_id"]
    return registry


def explicit_report(report, cohort="four-stack-v1"):
    result = copy.deepcopy(report)
    result["schema_version"] = 2
    result["benchmark"] = {"definition": "simple-api-v1", "cohort": cohort}
    result["metadata"]["api_health_policy"] = CONTAINER_HEALTHCHECK
    return result


def expanded_report(report, root=None):
    result = explicit_report(report, "synthetic-eight-v1")
    extension = json.loads((ROOT / "tests/fixtures/registry/extended.json").read_text())
    original = result["implementations"][0]
    for spec in extension["implementations"]:
        backend = copy.deepcopy(original)
        backend["implementation"] = spec["id"]
        result["implementations"].append(backend)
        result["metadata"]["versions"][spec["id"]] = {
            key: "1.2.3" for key in spec["version_fields"]
        }
        if root is not None:
            directory = root / result["metadata"]["artifact_directory"]
            for path in list(directory.glob(original["implementation"] + "-*")):
                target = directory / path.name.replace(original["implementation"], spec["id"], 1)
                target.write_bytes(path.read_bytes())
    return result


# Independent expectations: do not derive frozen cohort membership from the registry.
EIGHT_MEMBERS = (
    "go-gin",
    "go-echo",
    "rust-actix",
    "rust-axum",
    "node-fastify",
    "node-express",
    "python-fastapi",
    "python-flask",
)


def real_eight_report(report, root=None):
    """Expand synthetic data using real IDs; never read or write published results."""
    from benchmark.environment import registered_pinned_versions
    from benchmark.healthcheck import EXTERNAL_READINESS

    result = explicit_report(report, "eight-stack-v1")
    result["metadata"]["api_health_policy"] = EXTERNAL_READINESS
    original = result["implementations"][0]
    by_id = {backend["implementation"]: backend for backend in result["implementations"]}
    result["implementations"] = []
    versions = registered_pinned_versions()
    result["metadata"]["versions"] = {
        identifier: versions[identifier] for identifier in EIGHT_MEMBERS
    }
    for identifier in EIGHT_MEMBERS:
        backend = copy.deepcopy(by_id.get(identifier, original))
        backend["implementation"] = identifier
        result["implementations"].append(backend)
        if root is not None and identifier not in by_id:
            directory = root / result["metadata"]["artifact_directory"]
            for path in list(directory.glob(original["implementation"] + "-*")):
                target = directory / path.name.replace(original["implementation"], identifier, 1)
                target.write_bytes(path.read_bytes())
    return result
