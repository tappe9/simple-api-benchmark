"""Render both README result sections and charts from one verified official report."""

import argparse
import html
import re
import sys
from pathlib import Path

from .readme_charts import render_charts
from .registry import implementation
from .report import validate_report
from .results import BenchmarkFailure, require, strict_json

START = "<!-- benchmark-results:start -->"
END = "<!-- benchmark-results:end -->"
TESTS = {"/json": "JSON", "/db/42": "PostgreSQL", "/cpu": "CPU"}
CHART_ALT = {
    "json-throughput.svg": {
        "en": "JSON throughput comparison in requests per second",
        "ja": "JSONの処理件数/秒の比較",
    },
    "postgresql-throughput.svg": {
        "en": "PostgreSQL throughput comparison in requests per second",
        "ja": "PostgreSQLの処理件数/秒の比較",
    },
    "cpu-throughput.svg": {
        "en": "CPU throughput comparison in requests per second",
        "ja": "CPUの処理件数/秒の比較",
    },
}


def label(identifier: str) -> str:
    # Registry identity is trusted source, but labels must still be safe Markdown.
    value = html.escape(implementation(identifier)["display_name"])
    return re.sub(r"([\\`*_{}\[\]()#|])", r"\\\1", value)


def render(report: dict | None, locale: str) -> str:
    require(locale in ("en", "ja"), "unsupported README language")
    if report is None:
        return (
            "No verified official results have been published yet. Unavailable values are not zero."
            if locale == "en"
            else "確認済みの公式結果はまだありません。未計測の値をゼロとして表示しません。"
        )
    validate_report(report)
    context = report["metadata"]["github"]
    lines = [
        ("Measured (UTC)" if locale == "en" else "計測完了（UTC）")
        + ": `"
        + report["completed_at"]
        + "`",
        f"Source: `{report['metadata']['source_commit']}` · [Actions run]({context['run_url']})",
        "",
        (
            "1 CPU · 512 MiB · 1 worker · DB pool 10 · HTTP/1.1 · 50 connections · "
            "5 s warm-up · 3 × 30 s per endpoint. Middle-throughput whole run selected."
            if locale == "en"
            else "1 CPU・512 MiB・1 worker・DB pool 10・HTTP/1.1・50接続・warm-up 5秒・"
            "各endpointを30秒×3回。処理件数/秒が中央の1回から全指標を採用します。"
        ),
        "",
        ("### Throughput at a glance" if locale == "en" else "### スループット比較"),
        "",
    ]
    for filename in ("json-throughput.svg", "postgresql-throughput.svg", "cpu-throughput.svg"):
        lines.append(f"![{CHART_ALT[filename][locale]}](results/charts/{filename})")
        lines.append("")
    lines.extend(
        [
            "<details>",
            (
                "<summary>Full selected-run values</summary>"
                if locale == "en"
                else "<summary>選択されたrunの全数値</summary>"
            ),
            "",
            (
                "| Backend | Test | Requests/s ↑ | Mean response ms ↓ | Observed peak MiB ↓ |"
                if locale == "en"
                else "| バックエンド | テスト | 処理件数/秒 ↑ | 平均応答 ms ↓ | 観測最大メモリ MiB ↓ |"
            ),
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for backend in report["implementations"]:
        for endpoint in backend["endpoints"]:
            selected = endpoint["selected"]
            lines.append(
                f"| {label(backend['implementation'])} | {TESTS[endpoint['endpoint']]} | "
                f"{selected['requests_per_second']:,.3f} | {selected['mean_response_time_ms']:,.3f} | "
                f"{selected['peak_memory_bytes'] / 1048576:,.3f} |"
            )
    lines += [
        "",
        "</details>",
        "",
        (
            "↑ Higher is better; ↓ lower is better. Every chart starts at zero and compares only "
            "throughput within one endpoint. Memory samples cover only the API container, not "
            "PostgreSQL, and can miss brief peaks. These are complete-stack reference results on "
            "shared GitHub-hosted hardware, not universal language rankings."
            if locale == "en"
            else "↑ 多いほど高速、↓ 少ないほど良好です。各グラフはゼロ基準で、同一endpoint内の"
            "処理件数/秒だけを比較します。メモリはAPIコンテナだけの観測値で、PostgreSQLは含まず、"
            "短いピークを見逃す場合があります。共有GitHub-hosted環境でのAPIスタック全体の参考値であり、"
            "言語の普遍的な順位ではありません。"
        ),
        "",
        "[Result JSON](results/latest.json) · [History](results/history/) · "
        "[Detailed results site](https://tappe9.github.io/simple-api-benchmark/) · "
        "[Methodology](docs/METHODOLOGY.md) · [Versions and conditions](results/latest.json)",
    ]
    return "\n".join(lines)


def replace_section(source: str, section: str) -> str:
    require(source.count(START) == source.count(END) == 1, "README requires one marker pair")
    start = source.index(START) + len(START)
    end = source.index(END)
    require(start < end, "README markers reversed")
    return source[:start] + "\n\n" + section.strip() + "\n\n" + source[end:]


def generated_updates(root: Path, report: dict | None) -> dict[Path, str]:
    updates = {
        root / filename: replace_section(
            (root / filename).read_text(encoding="utf-8"), render(report, locale)
        )
        for filename, locale in (("README.md", "en"), ("README.ja.md", "ja"))
    }
    if report is not None:
        updates.update({root / name: content for name, content in render_charts(report).items()})
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="check generated sections and charts without writing"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        path = root / "results/latest.json"
        report = strict_json(path.read_bytes()) if path.exists() else None
        # Render every generated file before writing any; official publication uses one Git transaction.
        updates = generated_updates(root, report)
        for path, value in updates.items():
            if args.check:
                require(
                    path.is_file() and path.read_text(encoding="utf-8") == value,
                    f"stale generated file: {path.relative_to(root)}",
                )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
        return 0
    except (BenchmarkFailure, OSError, ValueError) as error:
        print(f"README generation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
