"""Keep implementation status in one registry-backed guide, not rollout snapshots."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STATUS = "IMPLEMENTATIONS.md#registered-and-measured-implementations"
GUIDE_SECTIONS = {
    "AXUM.md": "Status and comparison boundary",
    "FLASK.md": "Publication boundary",
    "JAVA-SPRING-BOOT.md": "Registration is not official measurement",
    "NODE-EXPRESS.md": None,
}


def section(text: str, heading: str) -> str:
    """Read one heading and its prose, without matching a whole paragraph."""
    match = re.search(rf"(?m)^#{{2,3}} {re.escape(heading)}\n", text)
    if match is None:
        raise AssertionError(f"Missing documentation section: {heading}")
    return re.split(r"(?m)^#{2,3} ", text[match.end() :], maxsplit=1)[0]


class ImplementationDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        cls.canonical = (DOCS / "IMPLEMENTATIONS.md").read_text()

    def assert_canonical_link(self, text, target):
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        self.assertIn(target, links)
        path, anchor = target.split("#", 1)
        destination = DOCS / path
        self.assertTrue(destination.is_file(), target)
        headings = re.findall(r"(?m)^#{1,6} (.+)$", destination.read_text())
        anchors = {
            re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings
        }
        self.assertIn(anchor, anchors, target)

    def test_status_sections_delegate_cohort_claims_to_canonical_guide(self):
        for filename, heading in GUIDE_SECTIONS.items():
            with self.subTest(guide=filename):
                text = (DOCS / filename).read_text()
                current = section(text, heading) if heading else text
                self.assert_canonical_link(current, STATUS)
                # Cohort identities belong in the shared guide, not per-guide snapshots.
                for cohort in self.registry["cohorts"]:
                    self.assertNotIn(f"`{cohort}`", current)

    def test_canonical_cohort_table_matches_registry_membership_and_active_pointer(self):
        rows = {}
        table = section(self.canonical, "Registered and measured implementations")
        for implementation in self.registry["implementations"]:
            self.assertIn(implementation["display_name"], table)
        for line in table.splitlines():
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) == 5 and cells[1].startswith("`"):
                cohort = cells[1].strip("`")
                self.assertNotIn(cohort, rows)
                rows[cohort] = (re.findall(r"`([^`]+)`", cells[2]), cells[3])
        self.assertEqual(set(rows), set(self.registry["cohorts"]))
        for cohort, expected in self.registry["cohorts"].items():
            with self.subTest(cohort=cohort):
                members, role = rows[cohort]
                self.assertEqual(members, expected["members"])
                self.assertEqual(
                    "Active official cohort" in role, cohort == self.registry["active_cohort"]
                )

    def test_ci_scope_is_registry_wide_and_axum_links_to_it(self):
        coverage = section(self.canonical, "CI coverage")
        self.assertRegex(" ".join(coverage.split()), r"all registered implementations")
        self.assertIn("benchmark.ci matrix", coverage)
        self.assertIn("`required`", coverage)
        axum = section((DOCS / "AXUM.md").read_text(), "Normal CI integration")
        self.assert_canonical_link(axum, "IMPLEMENTATIONS.md#ci-coverage")
        self.assertNotRegex(axum, r"\b\w+-implementation CI matrix\b")

    def test_flask_runtime_change_is_distinct_from_dated_measurement(self):
        boundary = section(self.canonical, "Published results and runtime changes")
        paragraphs = [" ".join(p.split()) for p in boundary.split("\n\n")]
        published = next((p for p in paragraphs if "2026-09-15" in p), "")
        self.assertRegex(published, r"Waitress(?:\s|`)+3\.0\.2")
        self.assertIn("source_commit", boundary)
        self.assertIn("Gunicorn", boundary)
        self.assertRegex(boundary, r"(?i)not.*Gunicorn.*measurement")
        self.assertIn("results/history/2026-09-15T04-14-09Z-34925168324-1.json", boundary)
        flask = section((DOCS / "FLASK.md").read_text(), "Publication boundary")
        self.assert_canonical_link(
            flask, "IMPLEMENTATIONS.md#published-results-and-runtime-changes"
        )

    def test_java_boundary_does_not_claim_official_results(self):
        java = " ".join(section(self.canonical, "Java registration boundary (#67)").split())
        self.assertIn("`java-spring-boot`", java)
        self.assertRegex(java, r"(?i)registered.*\bCI\b")
        self.assertRegex(java, r"(?i)not.*member.*official cohort")
        self.assertRegex(java, r"(?i)no official Java.*result")
        guide = section(
            (DOCS / "JAVA-SPRING-BOOT.md").read_text(), "Registration is not official measurement"
        )
        self.assert_canonical_link(guide, "IMPLEMENTATIONS.md#java-registration-boundary-67")


if __name__ == "__main__":
    unittest.main()
