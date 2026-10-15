"""MetricFlow's Python API on the dbt-duckdb adapter: compiles a structured request from the semantic definitions and
runs it read-only (target `metrics` in dbt/profiles.yml opens the warehouse with `access_mode: READ_ONLY`; the
connection closes after every query, so a running server never blocks `make all`)."""

import argparse
import contextlib
import functools
import sys
from dataclasses import dataclass
from pathlib import Path

from dbt.adapters.factory import get_adapter, register_adapter
from dbt.config.runtime import RuntimeConfig, load_profile, load_project
from dbt.flags import set_from_args
from dbt.mp_context import get_mp_context
from dbt_common.events.event_manager_client import cleanup_event_logger
from dbt_metricflow.cli.dbt_connectors.adapter_backed_client import AdapterBackedSqlClient
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.engine.models import Entity
from metricflow_semantic_interfaces.type_enums import DimensionType, EntityType
from metricflow_semantics.model.dbt_manifest_parser import parse_manifest_from_dbt_generated_manifest
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

TARGET = "metrics"
GRAINS = ("day", "week", "month", "quarter", "year")
METRIC_TIME = "metric_time"


@dataclass(frozen=True)
class GroupBy:
    name: str  # what agents send: an entity (`provider`), a dimension (`provider__pricing_model`) or `metric_time`
    kind: str  # entity, categorical or time
    grains: tuple[str, ...] = ()  # metric_time only: its base grain and the coarser ones


@functools.cache
def _adapter(dbt_dir: str):
    """The dbt-duckdb adapter of target `metrics`, built once per process without connecting. dbt's event loggers
    write to stdout, which is the MCP stdio channel: they are removed."""
    cleanup_event_logger()
    args = argparse.Namespace(profiles_dir=dbt_dir, project_dir=dbt_dir, target=TARGET, vars={}, threads=None)
    set_from_args(args, {})
    profile = load_profile(dbt_dir, {}, target_override=TARGET)
    project = load_project(dbt_dir, version_check=False, profile=profile)
    config = RuntimeConfig.from_parts(project, profile, args)
    register_adapter(config, get_mp_context())
    return get_adapter(config)


class Engine:
    """A MetricFlow engine on one semantic manifest."""

    def __init__(self, dbt_dir: Path, semantic_manifest_json: str):
        with contextlib.redirect_stdout(sys.stderr):  # stdout is the MCP stdio channel
            manifest = parse_manifest_from_dbt_generated_manifest(manifest_json_string=semantic_manifest_json)
            self._mf = MetricFlowEngine(SemanticManifestLookup(manifest),
                                        AdapterBackedSqlClient(_adapter(str(dbt_dir))))
        self._group_bys: dict[str, dict[str, GroupBy]] = {}

    def group_bys(self, metric_name: str) -> dict[str, GroupBy]:
        """What MetricFlow allows the metric to be grouped and filtered by: foreign entities, categorical
        dimensions and `metric_time`. Row-level primary entities and per-model time dimensions are left out."""
        if metric_name not in self._group_bys:
            allowed = {}
            for item in self._mf.list_group_bys(metric_names=[metric_name]):
                if isinstance(item, Entity):
                    if item.type is not EntityType.PRIMARY:
                        allowed[item.name] = GroupBy(item.name, "entity")
                elif item.type is DimensionType.CATEGORICAL:
                    allowed[item.dunder_name] = GroupBy(item.dunder_name, "categorical")
                elif item.dunder_name.startswith(f"{METRIC_TIME}__"):
                    base = item.dunder_name.removeprefix(f"{METRIC_TIME}__")
                    allowed[METRIC_TIME] = GroupBy(METRIC_TIME, "time", GRAINS[GRAINS.index(base):])
            self._group_bys[metric_name] = dict(sorted(allowed.items()))
        return self._group_bys[metric_name]

    def query(self, metric_name: str, group_by: list[str], where: list[str], limit: int):
        """(column names, rows) of the metric grouped by `group_by` (MetricFlow names), ordered by them."""
        request = MetricFlowQueryRequest.create(
            metric_names=[metric_name], group_by_names=group_by, where_constraints=where or None,
            order_by_names=group_by or None, limit=limit,
        )
        with contextlib.redirect_stdout(sys.stderr):
            result = self._mf.query(request)
        return list(result.result_df.column_names), [tuple(row) for row in result.result_df.rows]
