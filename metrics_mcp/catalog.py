"""The metric definitions as dbt wrote them: `semantic_manifest.json` (MetricFlow spec) and `manifest.json`.

A metric is served only when its semantic-layer `meta` carries a `metric_id`. Its fingerprint (A50) hashes the
resolved definition: the metric spec, its input metrics, the used measures with the entities and dimensions of
their semantic models and of the semantic models they join to, those models' node relations, and the SQL checksum
of every dbt model behind them.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Every check a metric can require (A52); the first three are required by every metric.
CHECKS = {
    "certified": "the metric is certified in its semantic definition; drafts are neither listed nor queryable",
    "lock": "the running definition's fingerprint equals metrics.lock.yml for the current version",
    "dbt_tests": "every dbt test on the metric's backing models and their upstream nodes passed in the last build",
    "differential": "the last `make verify` (Python reference engine vs the dbt expected charges) passed after the "
                    "last build",
}
BASELINE_CHECKS = ("certified", "lock", "dbt_tests")
UNITS = ("EUR minor units", "bps")
METRIC_ID = re.compile(r"^M\d{2}$")

# Keys that document a definition without changing what it computes; never part of a fingerprint.
_UNFINGERPRINTED = frozenset({"description", "label", "config", "metadata"})
_TEMPLATE = re.compile(r"\{\{\s*\w+\(\s*'(?:\w+__)?(\w+)'(?:\s*,\s*'\w+')?\s*\)\s*\}\}")


@dataclass(frozen=True)
class Paths:
    """Where the server reads its inputs and writes its audit log; tests point these at copies."""

    dbt_dir: Path
    semantic_manifest: Path
    manifest: Path
    run_results: Path
    lock: Path
    db: Path
    audit: Path
    dbt_project: Path

    @classmethod
    def at(cls, root: Path = ROOT) -> "Paths":
        target = root / "dbt" / "target"
        return cls(
            dbt_dir=root / "dbt",
            semantic_manifest=target / "semantic_manifest.json",
            manifest=target / "manifest.json",
            run_results=target / "run_results.json",
            lock=root / "metrics.lock.yml",
            db=root / "warehouse" / "fees.duckdb",
            audit=root / "warehouse" / "metrics_mcp_audit.jsonl",
            dbt_project=root / "dbt" / "dbt_project.yml",
        )


@dataclass(frozen=True)
class Metric:
    metric_id: str
    name: str
    label: str
    description: str
    type: str
    version: int
    owner: str
    certified: bool
    unit: str
    requires: tuple[str, ...]
    semantic_models: tuple[str, ...]  # the measures' semantic models and those they join to
    models: tuple[str, ...]  # unique ids of the dbt models behind `semantic_models`
    formula: str
    fingerprint: str


def _strip(value):
    """`value` without documentation keys, at every level."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _UNFINGERPRINTED}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def readable_filter(template: str) -> str:
    """`{{ Dimension('provider_cost__component') }} = 'markup'` → `component = 'markup'`."""
    return _TEMPLATE.sub(r"\1", template)


def _where(spec: dict | None) -> list[str]:
    return [w["where_sql_template"] for w in (spec or {}).get("where_filters", [])]


class Catalog:
    """Metrics by id, resolved from one pair of dbt artifacts."""

    def __init__(self, semantic_manifest: dict, manifest: dict):
        self.semantic_manifest = semantic_manifest
        self.manifest = manifest
        self._metrics = {m["name"]: m for m in semantic_manifest["metrics"]}
        self._models = {m["name"]: m for m in semantic_manifest["semantic_models"]}
        self._measure_models = {
            measure["name"]: model["name"] for model in semantic_manifest["semantic_models"]
            for measure in model["measures"]
        }
        self._dbt_models = {
            node["name"]: node["depends_on"]["nodes"][0] for node in manifest["semantic_models"].values()
        }
        self.metrics: dict[str, Metric] = {}
        self.problems: list[str] = []
        for raw in semantic_manifest["metrics"]:
            meta = (raw.get("config") or {}).get("meta") or {}
            if "metric_id" not in meta:
                continue
            metric = self._metric(raw, meta)
            if metric.metric_id in self.metrics:
                self.problems.append(f"{metric.metric_id} is the metric_id of both "
                                     f"{self.metrics[metric.metric_id].name} and {metric.name}")
            self.metrics[metric.metric_id] = metric

    @classmethod
    def load(cls, paths: Paths) -> "Catalog":
        for path in (paths.semantic_manifest, paths.manifest):
            if not path.exists():
                raise FileNotFoundError(f"{path} not found: run `make build`")
        return cls(json.loads(paths.semantic_manifest.read_text()), json.loads(paths.manifest.read_text()))

    def certified(self) -> list[Metric]:
        return [m for _, m in sorted(self.metrics.items()) if m.certified]

    # Resolution ----------------------------------------------------------------------------------------------

    def _input_metrics(self, raw: dict) -> list[dict]:
        """Every metric `raw` is computed from, recursively, without `raw` itself."""
        params = raw["type_params"]
        names = [i["name"] for i in [params.get("numerator"), params.get("denominator")] + params["metrics"] if i]
        found = []
        for name in names:
            child = self._metrics[name]
            found += [child] + self._input_metrics(child)
        return found

    def _semantic_models(self, raw: dict) -> list[str]:
        """The semantic models of the metric's measures, then those whose primary entity they join to."""
        direct = sorted({self._measure_models[m["name"]] for m in raw["type_params"]["input_measures"]})
        entities = {e["name"] for name in direct for e in self._models[name]["entities"]}
        joined = sorted(
            name for name, model in self._models.items() if name not in direct
            and any(e["type"] == "primary" and e["name"] in entities for e in model["entities"])
        )
        return direct + joined

    def _formula(self, raw: dict) -> str:
        params = raw["type_params"]

        def ref(metric_input: dict) -> str:
            child = self._metrics[metric_input["name"]]
            text = (child.get("config") or {}).get("meta", {}).get("metric_id", child["name"])
            filters = _where(metric_input.get("filter"))
            return text + "".join(f" where `{readable_filter(f)}`" for f in filters)

        if raw["type"] == "ratio":
            text = f"{ref(params['numerator'])} ÷ {ref(params['denominator'])}"
        else:
            measure = params["input_measures"][0]["name"]
            model = self._models[self._measure_models[measure]]
            spec = next(m for m in model["measures"] if m["name"] == measure)
            text = f"{spec['agg']}(`{model['node_relation']['alias']}.{spec.get('expr') or measure}`)"
        return text + "".join(f", where `{readable_filter(f)}`" for f in _where(raw.get("filter")))

    def _metric(self, raw: dict, meta: dict) -> Metric:
        semantic_models = self._semantic_models(raw)
        measures = {m["name"] for m in raw["type_params"]["input_measures"]}
        models = tuple(self._dbt_models[name] for name in semantic_models)
        resolved = {
            "metric": _strip(raw),
            "unit": meta.get("unit"),
            "inputs": [_strip(m) for m in self._input_metrics(raw)],
            "semantic_models": [
                _strip({**self._models[name],
                        "measures": [m for m in self._models[name]["measures"] if m["name"] in measures]})
                for name in semantic_models
            ],
            "model_checksums": {uid: self.manifest["nodes"][uid]["checksum"]["checksum"] for uid in models},
        }
        canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
        metric = Metric(
            metric_id=str(meta["metric_id"]),
            name=raw["name"],
            label=raw.get("label") or raw["name"],
            description=" ".join((raw.get("description") or "").split()),
            type=raw["type"],
            version=meta.get("version"),
            owner=meta.get("owner"),
            certified=meta.get("certified") is True,
            unit=meta.get("unit"),
            requires=tuple(meta.get("requires") or ()),
            semantic_models=tuple(semantic_models),
            models=models,
            formula=self._formula(raw),
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest()[:16],
        )
        self.problems += _meta_problems(metric)
        return metric

    # Lineage -------------------------------------------------------------------------------------------------

    def upstream(self, unique_ids) -> set[str]:
        """`unique_ids` and every node they depend on (models, seeds, snapshots, sources)."""
        seen, todo = set(), list(unique_ids)
        while todo:
            uid = todo.pop()
            if uid in seen:
                continue
            seen.add(uid)
            node = self.manifest["nodes"].get(uid)
            if node:
                todo += node["depends_on"].get("nodes", [])
        return seen

    def lineage_models(self, metric: Metric) -> list[str]:
        """Names of the dbt models the metric is computed from, upstream included."""
        return sorted(self.manifest["nodes"][uid]["name"] for uid in self.upstream(metric.models)
                      if uid.startswith("model."))

    def tests_for(self, metric: Metric) -> list[str]:
        """Unique ids of every dbt data or unit test that touches the metric's models or their upstream nodes."""
        lineage = self.upstream(metric.models)
        tests = [n for n in self.manifest["nodes"].values() if n["resource_type"] == "test"]
        tests += list(self.manifest.get("unit_tests", {}).values())
        return sorted(t["unique_id"] for t in tests if lineage & set(t["depends_on"]["nodes"]))


def _meta_problems(metric: Metric) -> list[str]:
    where = f"{metric.metric_id} ({metric.name})"
    problems = []
    if not METRIC_ID.match(metric.metric_id):
        problems.append(f"{where}: metric_id must look like M01")
    if not isinstance(metric.version, int) or isinstance(metric.version, bool) or metric.version < 1:
        problems.append(f"{where}: meta.version must be an integer >= 1")
    if metric.unit not in UNITS:
        problems.append(f"{where}: meta.unit must be one of {', '.join(UNITS)}")
    if not isinstance(metric.owner, str) or not metric.owner:
        problems.append(f"{where}: meta.owner is required")
    unknown = sorted(set(metric.requires) - set(CHECKS))
    missing = [c for c in BASELINE_CHECKS if c not in metric.requires]
    if unknown:
        problems.append(f"{where}: meta.requires names unknown checks {unknown}")
    if missing:
        problems.append(f"{where}: meta.requires must include {missing}")
    return problems
