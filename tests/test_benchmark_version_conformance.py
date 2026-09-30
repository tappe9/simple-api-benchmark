"""Shared version contract exercised through synthetic, never published reports."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from registry_fixtures import java_registry, java_report
from test_benchmark_publication import synthetic_report

from benchmark import registry
from benchmark.report import validate_report
from benchmark.results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]


class VersionConformanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.legacy = synthetic_report(Path(temporary.name))
        self.java = java_report(self.legacy)
        self.cases = json.loads((ROOT / "tests/fixtures/stack-versions.json").read_text())

    def test_shared_version_contract(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                source = self.java if case["implementation"] == "java-spring-boot" else self.legacy
                report = copy.deepcopy(source)
                report["metadata"]["versions"][case["implementation"]][case["field"]] = case[
                    "value"
                ]
                before = copy.deepcopy(report)
                with patch.object(registry, "REGISTRY", java_registry()):
                    if case["valid"]:
                        validate_report(report)
                    else:
                        with self.assertRaises(BenchmarkFailure):
                            validate_report(report)
                self.assertEqual(report, before)

    def test_extracted_java_build_survives_full_report_validation(self):
        self.assertEqual(
            self.java["metadata"]["versions"]["java-spring-boot"]["java"], "25.0.4.1+1"
        )
        before = copy.deepcopy(self.java)
        with patch.object(registry, "REGISTRY", java_registry()):
            validate_report(self.java)
        self.assertEqual(self.java, before)
        with self.assertRaises(BenchmarkFailure):
            validate_report(self.java)

    def test_java_fixture_does_not_bypass_integrity_checks(self):
        changes = [
            lambda r: r.update(mode="smoke"),
            lambda r: r.update(official=False),
            lambda r: r.update(status="failed"),
            lambda r: r["benchmark"].update(cohort="unknown-v1"),
            lambda r: r["benchmark"].update(definition="unknown-v1"),
            lambda r: r["implementations"].clear(),
            lambda r: r["implementations"][0]["endpoints"].pop(),
            lambda r: r["implementations"][0]["endpoints"][0]["runs"].pop(),
            lambda r: r["metadata"]["versions"]["java-spring-boot"].pop("java"),
            lambda r: r["metadata"]["versions"]["java-spring-boot"].pop("spring-boot"),
        ]
        with patch.object(registry, "REGISTRY", java_registry()):
            for change in changes:
                report = copy.deepcopy(self.java)
                change(report)
                with self.subTest(change=change), self.assertRaises(BenchmarkFailure):
                    validate_report(report)
