"""Metrics MCP server on the warehouse built by `make all`: the lock workflow, checks and refusals, the served values
against the marts, and an MCP round trip. The dbt artifacts a test changes are copies; nothing calls the network."""

import json
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import anyio
import duckdb
import pytest
from mcp import Client

from feeaudit import verify
from metrics_mcp import lock
from metrics_mcp.catalog import Catalog, Paths
from metrics_mcp.checks import READ_ONLY
from metrics_mcp.server import build
from metrics_mcp.service import MetricsService

PATHS = Paths.at()
DISPUTE_QUEUE_TEST = "test.fee_audit.unique_fct_dispute_queue_dispute_queue_id.f54de5ac2f"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in (PATHS.db, PATHS.semantic_manifest, PATHS.manifest, PATHS.run_results, PATHS.lock)),
    reason="run `make all` to build the warehouse and the dbt artifacts",
)


def sql(query: str, *params) -> list[tuple]:
    with duckdb.connect(str(PATHS.db), config=READ_ONLY) as con:
        return con.execute(query, list(params)).fetchall()


def bps(numerator: int, denominator: int) -> str:
    """The exact ratio of two sums in basis points, at the marts' scale."""
    value = Decimal(numerator) * 10000 / Decimal(denominator)
    return format(value.quantize(Decimal("0.0001"), ROUND_HALF_UP), "f")


@pytest.fixture(scope="module")
def service(tmp_path_factory) -> MetricsService:
    return MetricsService(replace(PATHS, audit=tmp_path_factory.mktemp("audit") / "audit.jsonl"))


@pytest.fixture
def paths(tmp_path) -> Paths:
    """Copies of the semantic manifest, manifest, run results and lock; the warehouse and dbt project are real."""
    copies = {}
    for field in ("semantic_manifest", "manifest", "run_results", "lock"):
        copies[field] = tmp_path / getattr(PATHS, field).name
        shutil.copy(getattr(PATHS, field), copies[field])
    return replace(PATHS, audit=tmp_path / "audit.jsonl", **copies)


def edit_json(path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def metric(data: dict, name: str) -> dict:
    return next(m for m in data["metrics"] if m["name"] == name)


def measure(data: dict, name: str) -> dict:
    return next(m for model in data["semantic_models"] for m in model["measures"] if m["name"] == name)


def change_recoverable(data: dict, version: int = 1) -> None:
    """A real definition change: M07 recoverable becomes the sum of every overcharge."""
    measure(data, "recoverable_minor")["expr"] = "overcharge_minor"
    metric(data, "recoverable")["config"]["meta"]["version"] = version


def assert_no_number(response: dict) -> None:
    assert response["status"] == "refused"
    assert "rows" not in response and "value" not in response


# Lock ----------------------------------------------------------------------------------------------------------


def test_committed_lock_matches_the_build():
    assert lock.check(Catalog.load(PATHS), PATHS.lock) == []


def test_changed_definition_without_bump_fails(paths):
    edit_json(paths.semantic_manifest, change_recoverable)
    catalog = Catalog.load(paths)
    before = paths.lock.read_text()
    problems = lock.check(catalog, paths.lock)
    assert len(problems) == 1
    assert problems[0].startswith("M07 (recoverable) definition changed")
    assert "bump the version to 2" in problems[0]
    assert lock.update(catalog, paths.lock) == problems  # update refuses too
    assert paths.lock.read_text() == before


def test_bump_without_lock_update_fails_and_update_accepts_it(paths):
    edit_json(paths.semantic_manifest, lambda d: change_recoverable(d, version=2))
    catalog = Catalog.load(paths)
    problems = lock.check(catalog, paths.lock)
    assert problems == ["M07 (recoverable) version bumped to 2 but metrics.lock.yml has 1: "
                        "run `python -m metrics_mcp lock --update`"]
    assert lock.update(catalog, paths.lock) == []
    assert lock.check(catalog, paths.lock) == []
    entries, original = lock.read(paths.lock), lock.read(PATHS.lock)
    assert entries["M07"]["version"] == 2 and entries["M07"]["fingerprint"] != original["M07"]["fingerprint"]
    assert {k: v for k, v in entries.items() if k != "M07"} == {k: v for k, v in original.items() if k != "M07"}


def test_version_skip_missing_and_extra_metrics(paths):
    edit_json(paths.semantic_manifest, lambda d: change_recoverable(d, version=3))
    entries = lock.read(PATHS.lock)
    entries["M99"] = entries.pop("M01")
    lock.write(paths.lock, entries)
    problems = lock.check(Catalog.load(paths), paths.lock)
    assert any(p.startswith("M07") and "must be exactly 2" in p for p in problems)
    assert any(p.startswith("M01 (processed_volume) is missing from metrics.lock.yml") for p in problems)
    assert any(p.startswith("M99 is in metrics.lock.yml but no metric defines it") for p in problems)


def test_fingerprint_ignores_prose_and_follows_model_sql(paths):
    original = Catalog.load(PATHS).metrics
    edit_json(paths.semantic_manifest, lambda d: metric(d, "recoverable").update(description="Reworded."))
    assert Catalog.load(paths).metrics["M07"].fingerprint == original["M07"].fingerprint
    edit_json(paths.manifest, lambda d: d["nodes"]["model.fee_audit.fct_dispute_queue"]["checksum"]
              .update(checksum="0" * 64))
    changed = Catalog.load(paths).metrics
    assert {i for i in original if changed[i].fingerprint != original[i].fingerprint} == {"M05", "M06", "M07"}


# Checks and refusals -------------------------------------------------------------------------------------------


def test_refuses_when_a_dbt_test_on_the_lineage_failed(paths):
    def fail(data):
        next(r for r in data["results"] if r["unique_id"] == DISPUTE_QUEUE_TEST)["status"] = "fail"
    edit_json(paths.run_results, fail)
    service = MetricsService(paths)
    response = service.query_metric("M07", group_by=["provider"])
    assert_no_number(response)
    assert response["reason"] == "check_failed"
    assert [c["check"] for c in response["failed_checks"]] == ["dbt_tests"]
    assert "unique_fct_dispute_queue_dispute_queue_id (fail)" in response["failed_checks"][0]["detail"]
    assert "make build" in response["fix"]
    assert service.query_metric("M01")["status"] == "ok"  # fct_dispute_queue is not in M01's lineage


def test_refuses_when_a_dbt_test_result_is_missing(paths):
    edit_json(paths.run_results, lambda d: d.update(
        results=[r for r in d["results"] if r["unique_id"] != DISPUTE_QUEUE_TEST]))
    response = MetricsService(paths).query_metric("M05")
    assert_no_number(response)
    assert "unique_fct_dispute_queue_dispute_queue_id (missing)" in response["failed_checks"][0]["detail"]


def test_refuses_when_verify_failed(paths, tmp_path):
    db = tmp_path / "fees.duckdb"
    with duckdb.connect(str(db)) as con:
        verify.record(con, False, "3 differences between reference.expected_charges and main.int_expected_charges")
    service = MetricsService(replace(paths, db=db))
    response = service.query_metric("M05")
    assert_no_number(response)
    assert response["reason"] == "check_failed"
    assert response["failed_checks"][0]["check"] == "differential"
    assert "the last `make verify` failed: 3 differences" in response["failed_checks"][0]["detail"]
    assert service.metric_health("M05")["healthy"] is False
    assert service.query_metric("M02")["status"] == "ok"  # M02 does not require the differential check


def test_refuses_a_verify_older_than_the_build(paths):
    later = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    edit_json(paths.run_results, lambda d: d["metadata"].update(generated_at=later))
    response = MetricsService(paths).query_metric("M08")
    assert_no_number(response)
    assert "ran before the last build" in response["failed_checks"][0]["detail"]


def test_draft_metric_is_neither_listed_nor_queryable(paths):
    edit_json(paths.semantic_manifest, lambda d: metric(d, "undercharge")["config"]["meta"].update(certified=False))
    service = MetricsService(paths)
    assert lock.check(Catalog.load(paths), paths.lock) == []  # certification is not part of the definition
    assert "M06" not in [m["metric_id"] for m in service.list_metrics()["metrics"]]
    for response in (service.query_metric("M06"), service.describe_metric("M06")):
        assert_no_number(response)
        assert response["reason"] == "not_certified"


def test_refuses_a_definition_that_does_not_match_the_lock(paths):
    edit_json(paths.semantic_manifest, change_recoverable)
    response = MetricsService(paths).query_metric("M07")
    assert_no_number(response)
    assert [c["check"] for c in response["failed_checks"]] == ["lock"]


def test_stale_version_is_refused(service):
    response = service.query_metric("M02", expected_version=2)
    assert_no_number(response)
    assert response["reason"] == "stale_version" and response["version"] == 1
    assert service.query_metric("M02", expected_version=1)["status"] == "ok"


@pytest.mark.parametrize("request_args, error", [
    ({"group_by": ["provider_cost__component"]}, "unknown group_by dimension 'provider_cost__component'"),
    ({"group_by": ["provider"], "filters": [{"dimension": "provider", "op": "eq", "value": "northgate' OR '1'='1"}]},
     "value \"northgate' OR '1'='1\" rejected"),
    ({"filters": [{"dimension": "provider", "op": "eq", "value": "{{ Dimension('x') }}"}]}, "rejected"),
    ({"filters": [{"dimension": "provider", "op": "like", "value": "north%"}]}, "op must be one of"),
    ({"filters": [{"dimension": "metric_time", "op": "gte", "value": "2026-01-01; select 1"}]}, "ISO date"),
    ({"filters": ["provider = 'northgate'"]}, "exactly dimension, op and value"),
    ({"time_grain": "day"}, "time_grain must be one of ['month', 'quarter', 'year']"),
    ({"limit": 0}, "limit must be an integer"),
])
def test_invalid_requests_are_refused(service, request_args, error):
    response = service.query_metric("M07", **request_args)
    assert_no_number(response)
    assert response["reason"] == "invalid_request"
    assert any(error in e for e in response["errors"]), response["errors"]


def test_unknown_metric_is_refused(service):
    response = service.query_metric("M11")
    assert_no_number(response)
    assert response["reason"] == "unknown_metric" and "M10" in response["fix"]


def test_every_call_is_audited(paths):
    service = MetricsService(paths)
    ok = service.query_metric("M07")
    service.query_metric("M07", expected_version=5)
    entries = [json.loads(line) for line in paths.audit.read_text().splitlines()]
    assert [(e["tool"], e["outcome"]) for e in entries] == [("query_metric", "ok"),
                                                            ("query_metric", "refused:stale_version")]
    assert entries[0]["query_hash"] == ok["query_hash"] and entries[0]["args"]["metric_id"] == "M07"


# Values against the marts --------------------------------------------------------------------------------------


def test_m02_provider_fees_equal_the_mart(service):
    response = service.query_metric("M02", group_by=["provider"])
    expected = dict(sql("select provider, sum(billed_minor) from main.fct_provider_costs group by 1"))
    assert {r["provider"]: r["value"] for r in response["rows"]} == expected
    assert all(type(r["value"]) is int for r in response["rows"])
    total = service.query_metric("M02")
    assert total["rows"] == [{"value": sql("select sum(billed_minor) from main.fct_provider_costs")[0][0]}]
    assert total["unit"] == "EUR minor units" and set(total["checks"]) == {"certified", "lock", "dbt_tests"}


def test_m01_processed_volume_equals_the_volume_in_provider_costs(service):
    volumes = dict(sql("""
        select provider, sum(volume_minor) from (
            select distinct provider, month, card_segment, volume_minor from main.fct_provider_costs
            where card_segment in ('eea_consumer', 'other')
        ) group by 1
    """))
    response = service.query_metric("M01", group_by=["provider"])
    assert {r["provider"]: r["value"] for r in response["rows"]} == volumes


def test_m03_effective_rate_is_the_ratio_of_sums_by_provider(service):
    billed = dict(sql("select provider, sum(billed_minor) from main.fct_provider_costs group by 1"))
    volume = dict(sql("select provider, sum(volume_minor) from main.fct_processed_volume group by 1"))
    response = service.query_metric("M03", group_by=["provider"])
    assert response["unit"] == "bps"
    expected = {p: bps(billed[p], volume[p]) if p in volume else None for p in billed}
    assert {r["provider"]: r["value"] for r in response["rows"]} == expected
    assert expected["kestrel"] is None  # payout fees, no card volume


def test_m04_markup_rate_equals_the_mart_rate_on_markup_rows(service):
    mart = {(str(month), segment): format(rate, "f") for month, segment, rate in sql("""
        select month, card_segment, effective_rate_bps from main.fct_provider_costs
        where component = 'markup' and card_segment in ('eea_consumer', 'other')
    """)}
    response = service.query_metric("M04", group_by=["card_segment"], time_grain="month",
                                    filters=[{"dimension": "card_segment", "op": "in",
                                              "value": ["eea_consumer", "other"]}])
    assert {(r["metric_time"], r["card_segment"]): r["value"] for r in response["rows"]} == mart


def test_m07_recoverable_equals_the_dispute_queue(service):
    expected = dict(sql("select provider, sum(recoverable_minor) from main.fct_dispute_queue group by 1"))
    response = service.query_metric("M07", group_by=["provider"])
    assert {r["provider"]: r["value"] for r in response["rows"]} == expected
    assert response["as_of_date"] == "2026-07-15"
    assert response["checks"] == {"certified": True, "lock": True, "dbt_tests": True, "differential": True}
    northgate = service.query_metric("M07", filters=[{"dimension": "provider", "op": "eq", "value": "northgate"}])
    assert northgate["rows"] == [{"value": expected["northgate"]}]


def test_m10_client_margin_equals_the_mart(service):
    expected = dict(sql("select client_id, sum(margin_minor) from main.fct_client_margin group by 1"))
    response = service.query_metric("M10", group_by=["client"])
    assert {r["client"]: r["value"] for r in response["rows"]} == expected
    total = service.query_metric("M10")
    assert total["rows"] == [{"value": sql("select sum(margin_minor) from main.fct_client_margin")[0][0]}]


def test_query_hash_is_stable_and_specific(service):
    first = service.query_metric("M07", group_by=["provider"])
    assert service.query_metric("M07", group_by=["provider"])["query_hash"] == first["query_hash"]
    assert service.query_metric("M07")["query_hash"] != first["query_hash"]


# MCP -----------------------------------------------------------------------------------------------------------


def test_mcp_round_trip(paths):
    async def session():
        async with Client(build(MetricsService(paths))) as client:
            tools = await client.list_tools()
            listed = await client.call_tool("list_metrics", {})
            answered = await client.call_tool("query_metric", {"metric_id": "M07", "group_by": ["provider"]})
            refused = await client.call_tool("query_metric", {"metric_id": "M07", "expected_version": 9})
            return tools, listed, answered, refused

    tools, listed, answered, refused = anyio.run(session)
    assert sorted(t.name for t in tools.tools) == ["describe_metric", "get_dimensions", "list_metrics",
                                                   "metric_health", "query_metric"]
    assert [m["metric_id"] for m in listed.structured_content["metrics"]] == [f"M{i:02d}" for i in range(1, 11)]
    expected = dict(sql("select provider, sum(recoverable_minor) from main.fct_dispute_queue group by 1"))
    assert {r["provider"]: r["value"] for r in answered.structured_content["rows"]} == expected
    assert json.loads(answered.content[0].text)["query_hash"] == answered.structured_content["query_hash"]
    assert refused.structured_content["reason"] == "stale_version"
