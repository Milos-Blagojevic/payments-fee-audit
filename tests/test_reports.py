"""Finance outputs and README blocks, on the warehouse built by `make all`."""

import csv
import io
import re
from pathlib import Path

import duckdb
import pytest

from feeaudit.reports import finance, readme, trace
from feeaudit.reports.common import eur

DB = Path("warehouse/fees.duckdb")
AS_OF = "2026-07-15"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="run `make all` to build the warehouse")


@pytest.fixture(scope="module")
def con():
    with duckdb.connect(str(DB), read_only=True) as connection:
        yield connection


@pytest.fixture(scope="module")
def packs(con):
    return finance.dispute_packs(con, AS_OF)


def _pack_rows(packs: dict, folder: str) -> list[dict]:
    csv.field_size_limit(1 << 30)  # provider × month findings list every line they cover
    return list(csv.DictReader(io.StringIO(packs[f"{folder}/findings.csv"])))


def test_one_pack_per_invoice_with_overcharges(con, packs):
    queue = finance.dispute_queue(con)
    assert queue
    expected = {f"dispute_packs/{q['provider']}/{q['dispute_queue_id']}/{n}" for q in queue
                for n in ("findings.csv", "letter.md")}
    assert set(packs) == expected


def test_pack_totals_match_findings_and_queue(con, packs):
    for q in finance.dispute_queue(con):
        folder = f"dispute_packs/{q['provider']}/{q['dispute_queue_id']}"
        pack = _pack_rows(packs, folder)
        total = sum(int(r["difference_minor"]) for r in pack)
        assert len(pack) == q["overcharge_findings"]
        assert total == q["overcharge_minor"]
        assert all(int(r["difference_minor"]) > 0 for r in pack)
        letter = packs[f"{folder}/letter.md"]
        assert f"**Total overcharge:** EUR {eur(total)}" in letter
        assert f"**Dispute deadline:** {q['earliest_deadline']}" in letter


def test_letter_cites_every_breached_clause(con, packs):
    for q in finance.dispute_queue(con):
        folder = f"dispute_packs/{q['provider']}/{q['dispute_queue_id']}"
        letter = packs[f"{folder}/letter.md"]
        breached = {f"{r['contract_id']} v{r['contract_version']} §{r['clause']}" for r in _pack_rows(packs, folder)}
        texts = dict(con.execute(
            "select contract_term_id, clause_text from main.dim_contract_terms where contract_term_id in "
            f"({', '.join('?' for _ in breached)})", sorted(breached)).fetchall())
        assert set(texts) == breached
        for term_id, text in texts.items():
            assert term_id in letter
            assert text in letter


def test_dispute_packs_never_include_anomaly_findings(con, packs):
    anomaly_ids = {r[0] for r in con.execute(
        "select finding_id from main.fct_findings where method = 'anomaly'").fetchall()}
    assert anomaly_ids  # the default world plants one anomaly that becomes a finding
    pack_ids = {r["finding_id"] for q in finance.dispute_queue(con)
                for r in _pack_rows(packs, f"dispute_packs/{q['provider']}/{q['dispute_queue_id']}")}
    assert pack_ids and not pack_ids & anomaly_ids
    methods = {r[0] for r in con.execute(
        f"select distinct method from main.fct_findings where finding_id in ({', '.join('?' for _ in pack_ids)})",
        sorted(pack_ids)).fetchall()}
    assert methods == {"rule"}


def test_findings_summary_keeps_anomalies_apart(con):
    md = finance.findings_summary(con, AS_OF)["findings_summary.md"]
    rules, anomalies = md.split("## Anomalies (not disputed)")
    found = finance.anomaly_findings(con)
    assert found and all(r["invoice_id"] in anomalies for r in found)
    assert "network_access_fee" not in rules and "network_access_fee" in anomalies
    rule_count = con.execute(
        "select count(*) from main.fct_findings where method = 'rule' and finding_type <> 'rounding'").fetchone()[0]
    assert finance.findings_overview(con)["findings"] == rule_count
    assert sum(r["findings"] for r in finance.findings_by_type(con)) == rule_count


def test_readme_anomaly_block_reports_the_planted_anomaly(con):
    block = readme.block_anomalies(con)
    for r in con.execute("select anomaly_id, first_detected_day from evaluation.anomaly_report "
                         "where category = 'planted' and detected").fetchall():
        assert f"{r[0]}: from" in block and f"caught on {r[1]}" in block


def test_follow_one_finding_agrees_with_fct_findings(con):
    t = trace.trace(con)
    f = t["finding"]
    row = con.execute(
        "select counterparty, finding_type, expected_minor, billed_minor, difference_minor, invoice_id, line_ids"
        " from main.fct_findings where finding_id = ?", [f["finding_id"]]).fetchone()
    assert row == (f["counterparty"], trace.FINDING_TYPE, f["expected_minor"], f["billed_minor"],
                   f["difference_minor"], f["invoice_id"], f["line_ids"])
    assert t["expected"]["expected_minor"] == f["expected_minor"]
    assert t["comparison"]["billed_minor"] == f["billed_minor"]
    assert t["stg"]["fee_minor"] == f["billed_minor"]
    assert t["raw"]["source_row"] == t["recon"]["source_row"]
    text = trace.render(con)
    for value in (f["finding_id"], f["invoice_id"], t["expected"]["formula"], f"EUR {eur(f['difference_minor'])}"):
        assert value in text


def test_readme_render_is_idempotent_and_strict():
    text = "a\n<!-- generated:x -->\nold\n<!-- /generated -->\nb\n<!-- generated:y -->\n<!-- /generated -->\n"
    once = readme.render(text, {"x": "new\n", "y": "| t |"})
    assert once == "a\n<!-- generated:x -->\nnew\n<!-- /generated -->\nb\n<!-- generated:y -->\n| t |\n<!-- /generated -->\n"
    assert readme.render(once, {"x": "new\n", "y": "| t |"}) == once
    with pytest.raises(KeyError):
        readme.render(text, {"x": "new"})
    with pytest.raises(KeyError):
        readme.render(text, {"x": "1", "y": "2", "z": "3"})


def test_readme_blocks_render_idempotently(con):
    blocks = readme.blocks(con, AS_OF)
    current = Path("README.md").read_text(encoding="utf-8")
    once = readme.render(current, blocks)
    assert readme.render(once, blocks) == once
    assert set(re.findall(r"<!-- generated:([\w-]+) -->", once)) == set(blocks)


def test_client_report_totals_match_margin_and_findings(con):
    from feeaudit.reports import client

    out = client.client_report(con)
    margin = list(csv.DictReader(io.StringIO(out["client_margin.csv"])))
    totals = client.margin_totals(con)
    for column in ("billed_minor", "revenue_leakage_minor", "provider_cost_minor", "margin_minor"):
        assert sum(int(r[column]) for r in margin) == totals[column]
    per_client = client.margin_by_client(con)
    assert sum(r["margin_minor"] for r in per_client) == totals["margin_minor"]
    findings = list(csv.DictReader(io.StringIO(out["client_findings.csv"])))
    count, net = con.execute(
        "select count(*), sum(difference_minor) from main.fct_client_billing_findings").fetchone()
    assert sum(int(r["findings"]) for r in findings) == count
    assert sum(int(r["difference_minor"]) for r in findings) == net
    by_type = client.leakage_by_type(con)
    assert sum(r["findings"] for r in by_type) == count
    assert sum(r["overbilled_minor"] - r["leakage_minor"] for r in by_type) == net
    text = out["client_report.md"]
    assert f"EUR {eur(totals['revenue_leakage_minor'])} of revenue leakage" in text
    assert f"the margin is EUR {eur(totals['margin_minor'])}" in text
