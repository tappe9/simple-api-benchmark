"""Invocation-policy changes must not invalidate archived scheduled results."""

import copy
import json
import unittest
from pathlib import Path

from benchmark.report import validate_report

ROOT = Path(__file__).resolve().parents[1]


class HistoricalInvocationTests(unittest.TestCase):
    def test_archived_scheduled_reports_keep_original_provenance(self):
        historical = []
        for path in sorted((ROOT / "results/history").glob("*.json")):
            original = path.read_bytes()
            report = json.loads(original)
            if report["metadata"]["github"]["event"] != "schedule":
                continue
            historical.append(path)
            before = copy.deepcopy(report)
            with self.subTest(report=path.name):
                validate_report(report)
                self.assertEqual(report, before)
                self.assertEqual(path.read_bytes(), original)
        self.assertTrue(historical, "retain archived scheduled-run evidence")


if __name__ == "__main__":
    unittest.main()
