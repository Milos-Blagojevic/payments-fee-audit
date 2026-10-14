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
