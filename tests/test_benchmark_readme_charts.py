"""README chart generation regressions."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_benchmark_publication import synthetic_report


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

    def test_readme_render_embeds_all_three_charts_with_accessible_fallback_table(self):
        from benchmark import generate_readme

        text = generate_readme.render(self.report, "en")
        self.assertIn("results/charts/json-throughput.svg", text)
        self.assertIn("results/charts/postgresql-throughput.svg", text)
        self.assertIn("results/charts/cpu-throughput.svg", text)
        self.assertIn("<details>", text)
        self.assertIn("| Backend | Test | Requests/s", text)
        self.assertIn("Result JSON", text)


if __name__ == "__main__":
    unittest.main()
