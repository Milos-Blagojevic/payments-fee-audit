"""The checks a metric must pass at query time (A52). Any failure is a refusal (A54); there is no freshness check
(A55)."""

import json
from dataclasses import dataclass
from datetime import datetime

import duckdb

from metrics_mcp import lock
from metrics_mcp.catalog import BASELINE_CHECKS, Catalog, Metric, Paths

VERIFICATION_TABLE = "verification.check_results"
# The configuration of the `metrics` dbt target: DuckDB refuses two connections to one file in one process with
# different configurations, so every read-only connection here uses this one.
READ_ONLY = {"access_mode": "READ_ONLY"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    fix: str = ""


def run_results(paths: Paths) -> dict | None:
    return json.loads(paths.run_results.read_text()) if paths.run_results.exists() else None


def built_at(results: dict | None) -> str | None:
    """When the last dbt invocation (`make build`) finished, from run_results.json."""
    return results["metadata"]["generated_at"] if results else None


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def certified(catalog: Catalog, metric: Metric, paths: Paths, results: dict | None) -> CheckResult:
    if metric.certified:
        return CheckResult("certified", True, "certified: true in the semantic definition")
    return CheckResult("certified", False, "the metric is a draft (meta.certified is not true)",
                       "certify it in dbt/models/semantic/_semantic.yml after review")


def lock_check(catalog: Catalog, metric: Metric, paths: Paths, results: dict | None) -> CheckResult:
    entry = lock.read(paths.lock).get(metric.metric_id)
    if entry is None:
        return CheckResult("lock", False, f"{metric.metric_id} is not in metrics.lock.yml", f"{lock.UPDATE}")
    if entry["version"] != metric.version:
        return CheckResult("lock", False,
                           f"definition is version {metric.version}, metrics.lock.yml has version {entry['version']}",
                           f"{lock.UPDATE} (allowed when the version is the locked version + 1)")
    if entry["fingerprint"] != metric.fingerprint:
        return CheckResult("lock", False,
                           f"definition fingerprint {metric.fingerprint} differs from the locked {entry['fingerprint']} "
                           f"for version {metric.version}",
                           f"bump meta.version to {metric.version + 1}, rebuild and {lock.UPDATE}")
    return CheckResult("lock", True, f"version {metric.version}, fingerprint {metric.fingerprint} as locked")


def dbt_tests(catalog: Catalog, metric: Metric, paths: Paths, results: dict | None) -> CheckResult:
    fix = "fix the failing dbt tests and run `make build`, then `make verify`"
    if results is None:
        return CheckResult("dbt_tests", False, f"{paths.run_results} not found", "run `make build`")
    tests = catalog.tests_for(metric)
    if not tests:
        return CheckResult("dbt_tests", False, "no dbt test covers the metric's models", "add dbt tests")
    status = {r["unique_id"]: r["status"] for r in results["results"]}
    failed = [(uid, status.get(uid, "missing")) for uid in tests if status.get(uid) != "pass"]
    if failed:
        listed = ", ".join(f"{uid.split('.')[2]} ({state})" for uid, state in failed[:5])
        more = f" and {len(failed) - 5} more" if len(failed) > 5 else ""
        return CheckResult("dbt_tests", False,
                           f"{len(failed)} of {len(tests)} dbt tests on the metric's lineage did not pass in the "
                           f"build of {built_at(results)}: {listed}{more}", fix)
    return CheckResult("dbt_tests", True, f"{len(tests)} of {len(tests)} dbt tests on the metric's lineage passed "
                                          f"in the build of {built_at(results)}")


def differential(catalog: Catalog, metric: Metric, paths: Paths, results: dict | None) -> CheckResult:
    fix = "run `make verify` after `make build`"
    if not paths.db.exists():
        return CheckResult("differential", False, f"{paths.db} not found", "run `make all`")
    try:
        with duckdb.connect(str(paths.db), config=READ_ONLY) as con:
            row = con.execute(f"select passed, detail, checked_at from {VERIFICATION_TABLE}"
                              " where check_name = 'differential'").fetchone()
    except duckdb.CatalogException:
        row = None
    except duckdb.IOException as error:  # a build holds the write lock
        return CheckResult("differential", False, f"warehouse not readable: {error}", "retry after the build")
    if row is None:
        return CheckResult("differential", False, f"no differential result in {VERIFICATION_TABLE}", fix)
    passed, detail, checked_at = row
    if not passed:
        return CheckResult("differential", False, f"the last `make verify` failed: {detail}",
                           "fix the differences between the reference engine and int_expected_charges, then "
                           + fix)
    if results is not None and checked_at < _utc(built_at(results)):
        return CheckResult("differential", False,
                           f"the last `make verify` ({checked_at:%Y-%m-%dT%H:%M:%SZ}) ran before the last build "
                           f"({built_at(results)})", fix)
    return CheckResult("differential", True, f"{detail} ({checked_at:%Y-%m-%dT%H:%M:%SZ})")


EVALUATORS = {"certified": certified, "lock": lock_check, "dbt_tests": dbt_tests, "differential": differential}


def evaluate(catalog: Catalog, metric: Metric, paths: Paths, results: dict | None) -> list[CheckResult]:
    """The baseline checks, then every other check the metric requires; an unknown check name fails."""
    unknown = "unknown check name in meta.requires", "fix meta.requires in dbt/models/semantic/_semantic.yml"
    names = dict.fromkeys(BASELINE_CHECKS + metric.requires)
    return [EVALUATORS[name](catalog, metric, paths, results) if name in EVALUATORS
            else CheckResult(name, False, *unknown) for name in names]
