"""Render deterministic, self-contained SVG throughput charts for README results."""

from html import escape

from .registry import implementation
from .report import validate_report
from .results import require

CHARTS = {
    "/json": ("results/charts/json-throughput.svg", "JSON"),
    "/db/42": ("results/charts/postgresql-throughput.svg", "PostgreSQL"),
    "/cpu": ("results/charts/cpu-throughput.svg", "CPU"),
}


def _selected_for(backend: dict, endpoint: str) -> dict:
    for result in backend["endpoints"]:
        if result["endpoint"] == endpoint:
            return result["selected"]
    raise AssertionError("validated report is missing an endpoint")


def _render_svg(report: dict, endpoint: str, title: str) -> str:
    rows = []
    for backend in report["implementations"]:
        identifier = backend["implementation"]
        value = _selected_for(backend, endpoint)["requests_per_second"]
        rows.append((escape(implementation(identifier)["display_name"]), value))
    require(bool(rows), "chart requires benchmark implementations")
    maximum = max(value for _, value in rows)
    require(maximum > 0, "chart throughput must be positive")

    width = 900
    label_x = 24
    bar_x = 230
    bar_width = 500
    value_x = 748
    top = 96
    row_height = 52
    bar_height = 22
    height = top + len(rows) * row_height + 56
    completed = escape(report["completed_at"])
    source = escape(report["metadata"]["source_commit"][:12])
    run_id = escape(str(report["metadata"]["github"]["run_id"]))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{escape(title)} throughput comparison</title>",
        (
            f"<desc>Zero-based requests per second comparison for {escape(title)}. "
            f"Measured {completed}; source {source}; Actions run {run_id}.</desc>"
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<g font-family="system-ui,-apple-system,Segoe UI,sans-serif" fill="#1f2328">',
        f'<text x="24" y="34" font-size="22" font-weight="700">{escape(title)} throughput</text>',
        f'<text x="24" y="58" font-size="13" fill="#57606a">requests/s · zero-based · measured {completed}</text>',
        f'<line x1="{bar_x}" y1="76" x2="{bar_x}" y2="{top + len(rows) * row_height - 12}" stroke="#8c959f" stroke-width="1"/>',
        f'<text x="{bar_x}" y="88" font-size="11" text-anchor="middle" fill="#57606a">0</text>',
    ]
    for index, (label, value) in enumerate(rows):
        y = top + index * row_height
        scaled = value / maximum * bar_width
        lines.extend(
            [
                f'<text x="{label_x}" y="{y + 17}" font-size="14">{label}</text>',
                f'<rect x="{bar_x}" y="{y}" width="{scaled:.3f}" height="{bar_height}" rx="4" fill="#0969da"/>',
                f'<text x="{value_x}" y="{y + 17}" font-size="13" font-variant-numeric="tabular-nums">{value:,.3f}</text>',
            ]
        )
    lines.extend(
        [
            f'<text x="{bar_x + bar_width}" y="{height - 20}" font-size="11" text-anchor="end" fill="#57606a">Higher is better ↑</text>',
            "</g>",
            "</svg>",
            "",
        ]
    )
    return "\n".join(lines)


def render_charts(report: dict) -> dict[str, str]:
    """Return all README chart paths and bytes-as-text from one verified report."""
    validate_report(report)
    return {
        path: _render_svg(report, endpoint, title)
        for endpoint, (path, title) in CHARTS.items()
    }
