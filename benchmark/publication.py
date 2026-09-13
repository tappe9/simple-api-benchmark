"""Define the exact file manifest for a verified benchmark publication."""

from .readme_charts import CHARTS
from .report import timestamp

FIXED_PUBLICATION_PATHS = frozenset({"README.md", "README.ja.md", "results/latest.json"})
CHART_PUBLICATION_PATHS = frozenset(path for path, _ in CHARTS.values())


def history_path(report: dict) -> str:
    date = timestamp(report["completed_at"]).strftime("%Y-%m-%dT%H-%M-%SZ")
    context = report["metadata"]["github"]
    return f"results/history/{date}-{context['run_id']}-{context['run_attempt']}.json"


def expected_publication_paths(report: dict) -> frozenset[str]:
    return frozenset(
        {
            *FIXED_PUBLICATION_PATHS,
            *CHART_PUBLICATION_PATHS,
            history_path(report),
        }
    )
