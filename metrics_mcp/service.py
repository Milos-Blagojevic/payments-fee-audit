"""The five tools as plain functions returning JSON-ready dicts: request validation, the checks, refusals and the
audit log. `server.py` exposes them over MCP; the README example and the tests call them directly."""

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import yaml

from metrics_mcp import checks
from metrics_mcp.catalog import CHECKS, Catalog, Metric, Paths
from metrics_mcp.engine import METRIC_TIME, Engine, GroupBy

# Structured filter operators (A56): every operator works on metric_time, the first four on the other dimensions.
OPS = {"eq": "=", "ne": "<>", "in": "in", "not_in": "not in", "gte": ">=", "lte": "<=", "gt": ">", "lt": "<"}
CATEGORICAL_OPS = ("eq", "ne", "in", "not_in")
LIST_OPS = ("in", "not_in")
# A filter value on an entity or categorical dimension: letters, digits, space and `_ . : @ -`, nothing else.
VALUE = re.compile(r"^[A-Za-z0-9_.:@ -]{1,64}$")
MAX_VALUES = 100
DEFAULT_LIMIT = 1000
MAX_LIMIT = 10_000
BPS_QUANTUM = Decimal("0.0001")  # the scale of `effective_rate_bps` in the marts


class Refusal(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload["reason"])
        self.payload = payload


def refusal(reason: str, metric_id, version, message: str, fix: str, failed_checks=(), errors=()) -> Refusal:
    """A refusal never carries a number (A54)."""
    return Refusal({
        "status": "refused",
        "metric_id": metric_id,
        "version": version,
        "reason": reason,
        "message": message,
        "failed_checks": [{"check": c.name, "detail": c.detail, "fix": c.fix} for c in failed_checks],
        "errors": list(errors),
        "fix": fix,
    })


def _money(value):
    """Minor units stay exact integers; anything else is a bug, not a number to round."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    raise TypeError(f"money value {value!r} is not an integer")


def _bps(value) -> str | None:
    """MetricFlow's ratio (a DOUBLE) as basis points in a decimal string, rounded half up to 4 places (A57)."""
    if value is None:
        return None
    return format((Decimal(value) * 10000).quantize(BPS_QUANTUM, ROUND_HALF_UP), "f")


def _cell(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class MetricsService:
    def __init__(self, paths: Paths | None = None):
        self.paths = paths or Paths.at()
        self._engine: Engine | None = None
        self._engine_key: str | None = None

    # Shared --------------------------------------------------------------------------------------------------

    def engine(self) -> Engine:
        """The MetricFlow engine of the current semantic manifest, rebuilt when the manifest changes."""
        text = self.paths.semantic_manifest.read_text()
        key = hashlib.sha256(text.encode()).hexdigest()
        if key != self._engine_key:
            self._engine, self._engine_key = Engine(self.paths.dbt_dir, text), key
        return self._engine

    def _metric(self, catalog: Catalog, metric_id) -> Metric:
        metric = catalog.metrics.get(metric_id) if isinstance(metric_id, str) else None
        if metric is None:
            ids = ", ".join(m.metric_id for m in catalog.certified())
            raise refusal("unknown_metric", metric_id, None, f"no metric {metric_id!r}",
                          f"call list_metrics; the metric ids are {ids}")
        if not metric.certified:
            raise refusal("not_certified", metric.metric_id, metric.version,
                          f"{metric.metric_id} ({metric.name}) is a draft: neither listed nor queryable",
                          "use a certified metric from list_metrics")
        return metric

    def as_of_date(self, results: dict | None) -> str:
        """The dbt var `as_of_date` the last build ran with (A22)."""
        build_vars = ((results or {}).get("args") or {}).get("vars") or {}
        if isinstance(build_vars, dict) and "as_of_date" in build_vars:
            return str(build_vars["as_of_date"])
        return str(yaml.safe_load(self.paths.dbt_project.read_text())["vars"]["as_of_date"])

    def _call(self, tool: str, args: dict, fn) -> dict:
        try:
            result = fn()
        except Refusal as r:
            result = r.payload
        except Exception as error:  # fail closed: no number on any unexpected error
            result = {"status": "error", "error": f"{type(error).__name__}: {error}"}
        self._audit(tool, args, result)
        return result

    def _audit(self, tool: str, args: dict, result: dict) -> None:
        status = result.get("status")
        outcome = f"refused:{result['reason']}" if status == "refused" else status
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "args": args,
            "outcome": outcome,
            "metric_id": result.get("metric_id"),
            "version": result.get("version"),
            "query_hash": result.get("query_hash"),
        }
        self.paths.audit.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.audit.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, default=str) + "\n")

    # Tools ---------------------------------------------------------------------------------------------------

    def list_metrics(self, search: str | None = None) -> dict:
        def run():
            catalog = Catalog.load(self.paths)
            needle = (search or "").lower()
            return {"status": "ok", "metrics": [
                {"metric_id": m.metric_id, "name": m.name, "label": m.label, "definition": m.description,
                 "unit": m.unit, "version": m.version, "owner": m.owner}
                for m in catalog.certified()
                if needle in " ".join((m.metric_id, m.name, m.label, m.description)).lower()
            ]}
        return self._call("list_metrics", {"search": search}, run)

    def describe_metric(self, metric_id: str) -> dict:
        def run():
            catalog = Catalog.load(self.paths)
            metric = self._metric(catalog, metric_id)
            allowed = self.engine().group_bys(metric.name)
            return {
                "status": "ok",
                "metric_id": metric.metric_id,
                "name": metric.name,
                "label": metric.label,
                "definition": metric.description,
                "formula": metric.formula,
                "type": metric.type,
                "unit": metric.unit,
                "owner": metric.owner,
                "version": metric.version,
                "fingerprint": metric.fingerprint,
                "group_by": list(allowed),
                "time_grains": list(allowed[METRIC_TIME].grains) if METRIC_TIME in allowed else [],
                "lineage": {
                    "semantic_models": list(metric.semantic_models),
                    "models": [uid.split(".")[-1] for uid in metric.models],
                    "upstream_models": catalog.lineage_models(metric),
                },
                "requires": [{"check": name, "why": CHECKS.get(name, "unknown check")} for name in metric.requires],
            }
        return self._call("describe_metric", {"metric_id": metric_id}, run)

    def get_dimensions(self, metric_id: str) -> dict:
        def run():
            catalog = Catalog.load(self.paths)
            metric = self._metric(catalog, metric_id)
            allowed = self.engine().group_bys(metric.name)
            return {
                "status": "ok",
                "metric_id": metric.metric_id,
                "version": metric.version,
                "dimensions": [
                    {"name": g.name, "kind": g.kind,
                     "filter_ops": list(OPS) if g.kind == "time" else list(CATEGORICAL_OPS),
                     **({"time_grains": list(g.grains), "filter_values": "ISO dates, YYYY-MM-DD"}
                        if g.kind == "time" else
                        {"filter_values": "strings of letters, digits, space and _ . : @ -, at most 64"})}
                    for g in allowed.values()
                ],
            }
        return self._call("get_dimensions", {"metric_id": metric_id}, run)

    def metric_health(self, metric_id: str) -> dict:
        def run():
            catalog = Catalog.load(self.paths)
            metric = self._metric(catalog, metric_id)
            results = checks.run_results(self.paths)
            evaluated = checks.evaluate(catalog, metric, self.paths, results)
            return {
                "status": "ok",
                "metric_id": metric.metric_id,
                "version": metric.version,
                "healthy": all(c.passed for c in evaluated),
                "checks": {c.name: {"passed": c.passed, "detail": c.detail, "fix": c.fix} for c in evaluated},
                "as_of_date": self.as_of_date(results),
                "built_at": checks.built_at(results),
            }
        return self._call("metric_health", {"metric_id": metric_id}, run)

    def query_metric(self, metric_id: str, group_by: list[str] | None = None, filters: list[dict] | None = None,
                     time_grain: str | None = None, limit: int | None = None,
                     expected_version: int | None = None) -> dict:
        args = {"metric_id": metric_id, "group_by": group_by, "filters": filters, "time_grain": time_grain,
                "limit": limit, "expected_version": expected_version}
        return self._call("query_metric", args, lambda: self.run_query(**args))

    # query_metric --------------------------------------------------------------------------------------------

    def run_query(self, metric_id: str, group_by: list[str] | None = None, filters: list[dict] | None = None,
                  time_grain: str | None = None, limit: int | None = None,
                  expected_version: int | None = None) -> dict:
        """`query_metric` without the audit log (the README example); raises `Refusal`."""
        catalog = Catalog.load(self.paths)
        metric = self._metric(catalog, metric_id)
        if expected_version is not None and expected_version != metric.version:
            raise refusal("stale_version", metric.metric_id, metric.version,
                          f"expected version {expected_version!r}, but {metric.metric_id} is served only at its "
                          f"current version {metric.version}",
                          f"re-read describe_metric({metric.metric_id!r}) and retry with expected_version="
                          f"{metric.version}")
        engine = self.engine()
        allowed = engine.group_bys(metric.name)
        request, errors = _validate(allowed, group_by, filters, time_grain, limit)
        if errors:
            raise refusal("invalid_request", metric.metric_id, metric.version, "the request is not valid",
                          f"group by or filter on {', '.join(allowed)} only; call get_dimensions"
                          f"({metric.metric_id!r})", errors=errors)

        results = checks.run_results(self.paths)
        as_of = self.as_of_date(results)
        query_hash = hashlib.sha256(json.dumps(
            {"metric_id": metric.metric_id, "version": metric.version, "fingerprint": metric.fingerprint,
             "as_of_date": as_of, **request}, sort_keys=True).encode()).hexdigest()[:16]
        evaluated = checks.evaluate(catalog, metric, self.paths, results)
        failed = [c for c in evaluated if not c.passed]
        if failed:
            payload = refusal("check_failed", metric.metric_id, metric.version,
                              f"{metric.metric_id} failed {', '.join(c.name for c in failed)}: no number is served",
                              "; ".join(c.fix for c in failed if c.fix), failed_checks=failed).payload
            raise Refusal({**payload, "query_hash": query_hash})

        grain = request["time_grain"]
        mf_group_by = [f"{METRIC_TIME}__{grain}" if g == METRIC_TIME else g for g in request["group_by"]]
        base_grain = allowed[METRIC_TIME].grains[0] if METRIC_TIME in allowed else None
        where = [_where_sql(f, allowed[f["dimension"]], base_grain) for f in request["filters"]]
        columns, rows = engine.query(metric.name, mf_group_by, where, request["limit"] + 1)
        value = _bps if metric.unit == "bps" else _money
        positions = [(agent, columns.index(mf)) for mf, agent in zip(mf_group_by, request["group_by"])]
        out = [{**{agent: _cell(row[i]) for agent, i in positions},
                "value": value(row[columns.index(metric.name)])} for row in rows[:request["limit"]]]
        return {
            "status": "ok",
            "metric_id": metric.metric_id,
            "name": metric.name,
            "version": metric.version,
            "unit": metric.unit,
            "group_by": request["group_by"],
            "time_grain": grain,
            "filters": request["filters"],
            "rows": out,
            "row_count": len(out),
            "truncated": len(rows) > request["limit"],
            "as_of_date": as_of,
            "built_at": checks.built_at(results),
            "checks": {c.name: c.passed for c in evaluated},
            "query_hash": query_hash,
        }


def _validate(allowed: dict[str, GroupBy], group_by, filters, time_grain, limit) -> tuple[dict, list[str]]:
    """The normalised request and every reason it is invalid. Only names MetricFlow allows for the metric, the
    operators of OPS and type-checked values get through (A56)."""
    errors = []
    group_by = [] if group_by is None else group_by
    filters = [] if filters is None else filters
    if not isinstance(group_by, list) or not all(isinstance(g, str) for g in group_by):
        errors.append("group_by must be a list of dimension names")
        group_by = []
    for name in group_by:
        if name not in allowed:
            errors.append(f"unknown group_by dimension {name!r}")
    if len(set(group_by)) != len(group_by):
        errors.append("group_by lists a dimension twice")
    grains = allowed[METRIC_TIME].grains if METRIC_TIME in allowed else ()
    if time_grain is not None:
        if time_grain not in grains:
            errors.append(f"time_grain must be one of {list(grains)}, not {time_grain!r}")
        elif METRIC_TIME not in group_by:
            group_by = [*group_by, METRIC_TIME]
    grain = (time_grain or grains[0]) if METRIC_TIME in group_by and grains else None

    normalised = []
    if not isinstance(filters, list):
        errors.append("filters must be a list of {dimension, op, value} objects")
        filters = []
    for i, f in enumerate(filters):
        where = f"filters[{i}]"
        if not isinstance(f, dict) or set(f) != {"dimension", "op", "value"}:
            errors.append(f"{where} must be an object with exactly dimension, op and value")
            continue
        dimension, op, value = f["dimension"], f["op"], f["value"]
        if not isinstance(dimension, str) or dimension not in allowed:
            errors.append(f"{where}: unknown dimension {dimension!r}")
            continue
        kind = allowed[dimension].kind
        ops = OPS if kind == "time" else CATEGORICAL_OPS
        if op not in ops:
            errors.append(f"{where}: op must be one of {list(ops)} for {dimension}, not {op!r}")
            continue
        values = value if op in LIST_OPS else [value]
        if op in LIST_OPS and (not isinstance(value, list) or not 1 <= len(value) <= MAX_VALUES):
            errors.append(f"{where}: op {op} needs a list of 1 to {MAX_VALUES} values")
            continue
        bad = [v for v in values if not _valid_value(kind, v)]
        if bad:
            rule = "an ISO date YYYY-MM-DD" if kind == "time" else \
                "a string of letters, digits, space and _ . : @ - (at most 64 characters)"
            errors.append(f"{where}: value {bad[0]!r} rejected; {dimension} takes {rule}")
            continue
        normalised.append({"dimension": dimension, "op": op, "value": value})

    if limit is None:
        limit = DEFAULT_LIMIT
    elif not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        errors.append(f"limit must be an integer from 1 to {MAX_LIMIT}")
        limit = DEFAULT_LIMIT
    return {"group_by": group_by, "filters": normalised, "time_grain": grain, "limit": limit}, errors


def _valid_value(kind: str, value) -> bool:
    if not isinstance(value, str):
        return False
    if kind == "time":
        try:
            return len(value) == 10 and date.fromisoformat(value) is not None
        except ValueError:
            return False
    return bool(VALUE.match(value))


def _where_sql(f: dict, group_by: GroupBy, base_grain: str | None) -> str:
    """A MetricFlow where filter from validated parts: the name is one MetricFlow listed and the values passed
    `_valid_value`; they are quoted all the same."""
    if group_by.kind == "entity":
        ref = f"{{{{ Entity('{group_by.name}') }}}}"
    elif group_by.kind == "categorical":
        ref = f"{{{{ Dimension('{group_by.name}') }}}}"
    else:
        ref = f"{{{{ TimeDimension('{METRIC_TIME}', '{base_grain}') }}}}"
    if f["op"] in LIST_OPS:
        literal = "(" + ", ".join(_quote(v) for v in f["value"]) + ")"
    else:
        literal = _quote(f["value"])
    return f"{ref} {OPS[f['op']]} {literal}"
