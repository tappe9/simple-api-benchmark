"""Keep the preparation boundary covered by dependency-free benchmark CI."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PreparationContractTests(unittest.TestCase):
    def test_result_pr_foundation_is_documented_but_not_activated(self):
        guide = ROOT / "docs/RESULT-PUBLICATION.md"
        self.assertTrue(guide.is_file(), "result-PR foundation needs an explicit cutover boundary")
        text = guide.read_text()
        for required in (
            "prepare_publication",
            "verify_candidate",
            "plan_merge",
            "reconcile_publication",
            "bypass_actors",
            "not a lock",
            "No live result-PR controller",
        ):
            self.assertIn(required, text)
        self.assertIn("RESULT-PUBLICATION.md", (ROOT / "ROADMAP.md").read_text())
        # This preparation change cannot silently connect a new privileged flow.
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            content = path.read_text()
            for forbidden in (
                "benchmark.result_pr",
                "create-github-app-token",
                "PUBLISHER_PRIVATE_KEY",
            ):
                self.assertNotIn(forbidden, content)


if __name__ == "__main__":
    unittest.main()
