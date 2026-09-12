"""README chart generation and publication regressions."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_benchmark_publication import END, START, context, synthetic_report


class ReadmeChartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = synthetic_report(self.root)

    def test_three_endpoint_throughput_svgs_are_deterministic_and_zero_based(self):
        from benchmark import readme_charts

        charts = readme_charts.render_charts(self.report)
        self.assertEqual(
            set(charts),
            {
                "results/charts/json-throughput.svg",
                "results/charts/postgresql-throughput.svg",
                "results/charts/cpu-throughput.svg",
            },
        )
        self.assertEqual(charts, readme_charts.render_charts(self.report))
        for path, svg in charts.items():
            with self.subTest(path=path):
                self.assertTrue(svg.startswith("<svg"))
                self.assertIn("viewBox=", svg)
                self.assertIn("requests/s", svg)
                self.assertIn(">0<", svg)
                self.assertIn("Go / Gin", svg)
                lower = svg.lower()
                self.assertNotIn("<script", lower)
                self.assertNotIn('href="http', lower)
                self.assertNotIn("url(http", lower)

    def test_chart_values_match_selected_run_and_escape_labels(self):
        from benchmark import readme_charts, registry

        data = registry.load_registry()
        mutated = {**data, "implementations": [dict(item) for item in data["implementations"]]}
        mutated["implementations"][0] = {
            **mutated["implementations"][0],
            "display_name": "<unsafe & label>",
        }
        with mock.patch.object(registry, "REGISTRY", mutated):
            svg = readme_charts.render_charts(self.report)["results/charts/json-throughput.svg"]
        selected = self.report["implementations"][0]["endpoints"][0]["selected"]
        self.assertIn(f"{selected['requests_per_second']:,.3f}", svg)
        self.assertIn("&lt;unsafe &amp; label&gt;", svg)
        self.assertNotIn("<unsafe", svg)

    def test_both_readmes_embed_three_charts_with_accessible_fallback_table(self):
        from benchmark import generate_readme

        for locale, table_header in (
            ("en", "| Backend | Test | Requests/s"),
            ("ja", "| バックエンド | テスト | 処理件数/秒"),
        ):
            with self.subTest(locale=locale):
                text = generate_readme.render(self.report, locale)
                self.assertIn("results/charts/json-throughput.svg", text)
                self.assertIn("results/charts/postgresql-throughput.svg", text)
                self.assertIn("results/charts/cpu-throughput.svg", text)
                self.assertIn("<details>", text)
                self.assertIn(table_header, text)
                self.assertIn("Result JSON", text)


class PublicationChartTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd or self.repo).decode().strip()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Chart publication test")
        self.git("config", "user.email", "test@example.invalid")
        for filename in ("README.md", "README.ja.md"):
            (self.repo / filename).write_text(f"intro\n{START}\nold\n{END}\noutro\n")
        (self.repo / ".gitignore").write_text(".cache/\n")
        (self.repo / "results").mkdir()
        (self.repo / "results/latest.json").write_text('{"previous":"verified bytes"}\n')
        self.git("add", ".")
        self.git("commit", "-qm", "test: initial verified state")
        self.source = self.git("rev-parse", "HEAD")
        self.git("init", "-q", "--bare", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "HEAD:main")
        self.report = synthetic_report(self.repo, source=self.source)
        self.report["metadata"]["source_tree"] = self.git("rev-parse", "HEAD^{tree}")

    def test_publication_commit_allowlists_all_three_charts_with_results(self):
        from benchmark import publish

        commit = publish.publish(self.report, self.repo, expected_context=context(self.source))
        changed = set(
            self.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        )
        history = {path for path in changed if path.startswith("results/history/")}
        charts = {
            "results/charts/json-throughput.svg",
            "results/charts/postgresql-throughput.svg",
            "results/charts/cpu-throughput.svg",
        }
        self.assertEqual(len(history), 1)
        self.assertEqual(
            changed,
            {"README.md", "README.ja.md", "results/latest.json", *history, *charts},
        )
        for path in charts:
            self.assertTrue(self.git("show", f"{commit}:{path}").startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
