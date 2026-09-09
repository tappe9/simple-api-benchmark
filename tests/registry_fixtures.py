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
