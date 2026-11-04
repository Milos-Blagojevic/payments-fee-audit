"""The MCP server (stdio): five read-only tools over `MetricsService`."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from metrics_mcp.service import CATEGORICAL_OPS, MAX_LIMIT, OPS, MetricsService

INSTRUCTIONS = """\
Certified payment-fee metrics (M01–M10) of a synthetic payments company, from dbt semantic definitions.
You never write SQL: pick a metric (list_metrics), read its definition and allowed dimensions (describe_metric,
get_dimensions), then query_metric with group_by and structured filters. Money is in EUR minor units (cents) as
exact integers; rates are basis points as decimal strings. A response with status "refused" means a verification
check failed or the request was invalid: it carries the reason and the fix, never a number. Quote metric_id,
version and query_hash with any number you report."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def build(service: MetricsService | None = None) -> MCPServer:
    service = service or MetricsService()
    server = MCPServer("payments-fee-metrics", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def list_metrics(
        search: Annotated[str | None, Field(description="Case-insensitive text to match in id, name or definition")]
        = None,
    ) -> dict[str, Any]:
        """List the certified metrics: id, name, definition, unit, version and owner."""
        return service.list_metrics(search)

    @server.tool(annotations=READ_ONLY)
    def describe_metric(metric_id: Annotated[str, Field(description="Metric id, e.g. M02")]) -> dict[str, Any]:
        """A metric's definition, formula, unit, owner, version, allowed group-by dimensions, time grains, lineage
        (semantic and dbt models) and the checks it must pass before any number is served."""
        return service.describe_metric(metric_id)

    @server.tool(annotations=READ_ONLY)
    def get_dimensions(metric_id: Annotated[str, Field(description="Metric id, e.g. M02")]) -> dict[str, Any]:
        """The dimensions a metric can be grouped and filtered by, with their filter operators and value rules."""
        return service.get_dimensions(metric_id)

    @server.tool(annotations=READ_ONLY)
    def query_metric(
        metric_id: Annotated[str, Field(description="Metric id, e.g. M07")],
        group_by: Annotated[list[str] | None, Field(description="Dimension names from get_dimensions")] = None,
        filters: Annotated[list[dict[str, Any]] | None, Field(description=(
            "Objects {dimension, op, value}. op: one of " + ", ".join(OPS) + " on metric_time (ISO dates), "
            + ", ".join(CATEGORICAL_OPS) + " on other dimensions; in and not_in take a list of values."
        ))] = None,
        time_grain: Annotated[str | None, Field(description="Grain of metric_time, e.g. month; adds metric_time to "
                                                            "group_by")] = None,
        limit: Annotated[int | None, Field(description=f"Maximum rows, 1 to {MAX_LIMIT} (default 1000)")] = None,
        expected_version: Annotated[int | None, Field(description="Refuse unless the metric is at this version")]
        = None,
    ) -> dict[str, Any]:
        """The metric's value by the requested dimensions, after every required check passed. Money values are
        integers in EUR minor units; bps values are decimal strings. Refuses (status "refused") instead of
        answering when a check fails or the request is invalid."""
        return service.query_metric(metric_id, group_by, filters, time_grain, limit, expected_version)

    @server.tool(annotations=READ_ONLY)
    def metric_health(metric_id: Annotated[str, Field(description="Metric id, e.g. M05")]) -> dict[str, Any]:
        """Every check the metric requires, each with its outcome, detail and fix; the build time and as_of_date."""
        return service.metric_health(metric_id)

    return server
