"""History publication tests for the verified Pages artifact."""

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.results import BenchmarkFailure
from benchmark.site import build

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("index.html", "style.css", "app.mjs", "registry.mjs")


class HistorySiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "site").mkdir()
        for name in ASSETS:
            (self.root / "site" / name).write_bytes((ROOT / "site" / name).read_bytes())
        (self.root / "results/history").mkdir(parents=True)
        self.latest = (ROOT / "results/latest.json").read_bytes()
        (self.root / "results/latest.json").write_bytes(self.latest)
        self.history_sources = sorted((ROOT / "results/history").glob("*.json"))
        for source in self.history_sources:
            (self.root / "results/history" / source.name).write_bytes(source.read_bytes())
        self.output = self.root / ".cache/site"

    def index(self):
        return json.loads((self.output / "results/history/index.json").read_text())

    def test_verified_history_is_allowlisted_and_indexed_deterministically(self):
        build(self.root)
        index = self.index()
        self.assertEqual(index["schema_version"], 1)
        self.assertEqual(len(index["runs"]), len(self.history_sources))
        self.assertEqual(
            [entry["completed_at"] for entry in index["runs"]],
            sorted((entry["completed_at"] for entry in index["runs"]), reverse=True),
        )
        ids = [entry["id"] for entry in index["runs"]]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in index["runs"]:
            self.assertRegex(entry["id"], r"^[1-9][0-9]*-[1-9][0-9]*$")
            self.assertRegex(entry["path"], r"^\./results/history/[0-9TZ-]+-[1-9][0-9]*-[1-9][0-9]*\.json$")
            published = self.output / entry["path"].removeprefix("./")
            self.assertTrue(published.is_file())
        files = {path.relative_to(self.output).as_posix() for path in self.output.rglob("*") if path.is_file()}
        expected_history = {f"results/history/{source.name}" for source in self.history_sources}
        self.assertEqual(
            files,
            {*ASSETS, ".nojekyll", "results/latest.json", "results/history/index.json", *expected_history},
        )

    def test_empty_history_publishes_an_empty_index(self):
        for path in (self.root / "results/history").iterdir():
            path.unlink()
        build(self.root)
        self.assertEqual(self.index(), {"schema_version": 1, "runs": []})

    def test_single_history_run_is_indexed_and_published(self):
        keep = self.history_sources[0].name
        for path in (self.root / "results/history").iterdir():
            if path.name != keep:
                path.unlink()
        build(self.root)
        runs = self.index()["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(Path(runs[0]["path"]).name, keep)
        self.assertTrue((self.output / runs[0]["path"].removeprefix("./")).is_file())

    def test_duplicate_run_identity_is_rejected_without_replacing_previous_site(self):
        build(self.root)
        previous = (self.output / "index.html").read_bytes()
        source = self.history_sources[0]
        duplicate = self.root / "results/history/2099-01-01T00-00-00Z-999999-1.json"
        report = json.loads(source.read_bytes())
        context = report["metadata"]["github"]
        duplicate_name = f"2099-01-01T00-00-00Z-{context['run_id']}-{context['run_attempt']}.json"
        duplicate = duplicate.with_name(duplicate_name)
        duplicate.write_text(json.dumps(report))
        with self.assertRaises(BenchmarkFailure):
            build(self.root)
        self.assertEqual((self.output / "index.html").read_bytes(), previous)

    def test_malformed_unsupported_and_identity_mismatched_history_are_rejected(self):
        cases = []
        source = self.history_sources[0]
        report = json.loads(source.read_bytes())

        malformed = ("2099-01-01T00-00-00Z-900001-1.json", b"not json")
        cases.append(malformed)

        unsupported_report = json.loads(source.read_bytes())
        unsupported_report["schema_version"] = 999
        cases.append(("2099-01-01T00-00-00Z-900002-1.json", json.dumps(unsupported_report).encode()))

        mismatch_report = json.loads(source.read_bytes())
        cases.append(("2099-01-01T00-00-00Z-900003-1.json", json.dumps(mismatch_report).encode()))

        for filename, content in cases:
            target = self.root / "results/history" / filename
            target.write_bytes(content)
            with self.subTest(filename=filename), self.assertRaises(BenchmarkFailure):
                build(self.root)
            target.unlink()

    def test_unexpected_files_symlinks_and_oversized_history_are_rejected(self):
        unexpected = self.root / "results/history/notes.txt"
        unexpected.write_text("not public")
        with self.assertRaises(BenchmarkFailure):
            build(self.root)
        unexpected.unlink()

        link = self.root / "results/history/2099-01-01T00-00-00Z-900004-1.json"
        link.symlink_to(self.root / "results/latest.json")
        with self.assertRaises(BenchmarkFailure):
            build(self.root)
        link.unlink()

        oversized = self.root / "results/history/2099-01-01T00-00-00Z-900005-1.json"
        oversized.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(BenchmarkFailure):
            build(self.root)


if __name__ == "__main__":
    unittest.main()
