"""Metrics MCP server: the certified metrics M01–M10 of the dbt semantic layer, for AI agents.

Agents never write SQL: they name a metric, group-by dimensions and structured filters; MetricFlow compiles the
query from the definitions in `dbt/models/semantic/` and runs it read-only against the warehouse. Every answer
carries the metric's version and the checks it passed; a failed check is a refusal, never a number.
"""
