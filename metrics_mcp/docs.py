"""Generated documentation: the METRICS.md table, from the same definitions the server serves, and the README
example, from a real query. `make report` writes both."""

import json

from metrics_mcp.catalog import Catalog
from metrics_mcp.service import MetricsService, Refusal

EXAMPLE = {"metric_id": "M07", "group_by": ["provider"]}
BUILT_AT = "<time of the last dbt build>"  # keeps the README identical from one build to the next


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def metrics_table(service: MetricsService | None = None) -> str:
    """One row per metric of the semantic layer, drafts marked."""
    service = service or MetricsService()
    catalog = Catalog.load(service.paths)
    engine = service.engine()
    rows = [
        [
            m.metric_id + ("" if m.certified else " (draft)"),
            f"{m.label} (`{m.name}`)",
            m.description,
            m.formula,
            m.unit,
            str(m.version),
            ", ".join(f"`{g}`" for g in engine.group_bys(m.name)),
            ", ".join(m.requires),
        ]
        for _, m in sorted(catalog.metrics.items())
    ]
    return _md_table(["Id", "Metric", "Definition", "Computed as", "Unit", "Version", "Group by", "Checks"], rows)


def readme_example(service: MetricsService | None = None) -> str:
    """A `query_metric` request and the server's response, then a refused request."""
    service = service or MetricsService()
    response = {**service.run_query(**EXAMPLE), "built_at": BUILT_AT}
    stale = {**EXAMPLE, "expected_version": response["version"] + 1}
    try:
        service.run_query(**stale)
    except Refusal as refused:
        refusal = refused.payload
    else:
        raise AssertionError("a request for another version was answered")
    return "\n\n".join([
        "Request, `query_metric`:",
        "```json\n" + json.dumps(EXAMPLE) + "\n```",
        "Response:",
        "```json\n" + json.dumps(response, indent=2) + "\n```",
        "The same request for another version is refused, without a number:",
        "```json\n" + json.dumps(stale) + "\n```",
        "```json\n" + json.dumps(refusal, indent=2) + "\n```",
    ])
