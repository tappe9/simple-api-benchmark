"""Static-site tests reuse a published report only as read-only test input."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path

from benchmark.results import BenchmarkFailure

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("index.html", "style.css", "app.mjs")


class SiteBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "site").mkdir()
        for name in ASSETS:
            (self.root / "site" / name).write_text("isolated test asset: " + name)
        (self.root / "results").mkdir()
        self.raw = (ROOT / "results/latest.json").read_bytes()
        (self.root / "results/latest.json").write_bytes(self.raw)
        self.output = self.root / ".cache/site"

    def build(self):
        try:
            module = importlib.import_module("benchmark.site")
        except ModuleNotFoundError:
            self.fail("benchmark.site must implement the validated static-site build")
        return module.build(self.root)

    def previous(self):
        self.output.mkdir(parents=True)
        (self.output / "index.html").write_bytes(b"previous site")

    def test_validated_json_is_copied_byte_for_byte_without_changing_sources(self):
        self.assertEqual(self.build(), self.output)
        self.assertEqual((self.output / "results/latest.json").read_bytes(), self.raw)
        self.assertEqual((self.root / "results/latest.json").read_bytes(), self.raw)
        for name in ASSETS:
            self.assertEqual(
                (self.output / name).read_bytes(), (self.root / "site" / name).read_bytes()
            )
        self.assertTrue((self.output / ".nojekyll").is_file())
        self.assertEqual(
            {p.relative_to(self.output).as_posix() for p in self.output.rglob("*") if p.is_file()},
            {*ASSETS, ".nojekyll", "results/latest.json"},
        )

    def test_unofficial_partial_and_tampered_reports_preserve_previous_build(self):
        self.previous()
        for mutation in ("local", "smoke", "partial", "selected", "conditions"):
            report = json.loads(self.raw)
            if mutation == "local":
                report["official"] = False
            elif mutation == "smoke":
                report["mode"] = "smoke"
            elif mutation == "partial":
                report["implementations"].pop()
            elif mutation == "selected":
                report["implementations"][0]["endpoints"][0]["selected"]["memory_samples"] += 1
            else:
                report["conditions"]["duration_seconds"] = 2
            (self.root / "results/latest.json").write_text(json.dumps(report))
            with self.subTest(mutation=mutation), self.assertRaises(BenchmarkFailure):
                self.build()
            self.assertEqual((self.output / "index.html").read_bytes(), b"previous site")

    def test_missing_report_builds_the_shell_without_fake_or_stale_data(self):
        self.build()
        (self.root / "results/latest.json").unlink()
        self.build()
        self.assertTrue((self.output / "index.html").exists())
        self.assertFalse((self.output / "results/latest.json").exists())
        self.assertFalse((self.root / "results/latest.json").exists())

    def test_duplicate_keys_and_invalid_json_do_not_replace_previous_build(self):
        self.previous()
        for raw in (b'{"official":true,"official":false}', b'{"value":NaN}', b'not json'):
            (self.root / "results/latest.json").write_bytes(raw)
            with self.assertRaises(BenchmarkFailure):
                self.build()
            self.assertEqual((self.output / "index.html").read_bytes(), b"previous site")

    def test_missing_and_symlinked_inputs_fail_before_replacing_output(self):
        self.previous()
        path = self.root / "site/app.mjs"
        path.unlink()
        with self.assertRaises(BenchmarkFailure):
            self.build()
        path.symlink_to(self.root / "results/latest.json")
        with self.assertRaises(BenchmarkFailure):
            self.build()
        self.assertEqual((self.output / "index.html").read_bytes(), b"previous site")

    def test_symlinked_output_is_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_bytes(b"untouched")
        self.output.parent.mkdir()
        self.output.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(BenchmarkFailure):
            self.build()
        self.assertEqual(sentinel.read_bytes(), b"untouched")

    def test_rebuild_replaces_only_owned_output_and_does_not_copy_extra_files(self):
        (self.root / "site/private.txt").write_text("not a public asset")
        self.build()
        (self.output / "stale.txt").write_text("old")
        (self.root / ".cache/keep.txt").write_text("unrelated cache")
        self.build()
        self.assertFalse((self.output / "stale.txt").exists())
        self.assertFalse((self.output / "private.txt").exists())
        self.assertEqual((self.root / ".cache/keep.txt").read_text(), "unrelated cache")


if __name__ == "__main__":
    unittest.main()
