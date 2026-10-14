"""Evaluation against truth on tiny hand-built warehouses."""

import duckdb
import pytest

from feeaudit.evaluation.__main__ import main
from feeaudit.evaluation.evaluate import evaluate

FINDING_COLS = """finding_id VARCHAR, party VARCHAR, counterparty VARCHAR, finding_type VARCHAR, event_id VARCHAR,
    line_ids VARCHAR[], contract_id VARCHAR, contract_version VARCHAR, clause VARCHAR, expected_minor BIGINT,
    billed_minor BIGINT, difference_minor BIGINT, currency VARCHAR, formula VARCHAR, evidence VARCHAR,
    invoice_date DATE, dispute_deadline DATE, days_left INTEGER, method VARCHAR, month DATE"""

# discrepancy_id, truth_id, provider, month, event_id, line_ids, difference_minor
DISCREPANCIES = [
    ("X1", "D01", "northgate", "2026-03", "P1", ["NG-1"], 40),  # found
    ("X2", "D03", "northgate", "2026-03", "P2", ["NG-2"], 25),  # missed
    ("X3", "D02", "northgate", "2026-03", None, ["NG-30", "NG-31"], 900),  # month-level, found
    ("X4", "D07", "brightpay", "2026-04", "P4", ["BP-4"], 60),  # found twice
    ("X5", "D08", "brightpay", "2026-04", "P5", ["BP-5"], 30),  # wrong type on the right line
    ("X6", "D04", "brightpay", "2026-04", "R1", ["BP-6"], 50),  # by refund event
]
NOISE = [("N01", "ng.csv", 9, "NG-9", "P9"), ("N08", "bp.csv", 1, "BP-1", "P11")]

# finding_id, counterparty, finding_type, event_id, line_ids, difference_minor, month
MESSY = [
    ("F1", "northgate", "stale_rate", "P1", ["NG-1"], 40, "2026-03-01"),
    ("F3", "northgate", "retroactive_tier_not_applied", None, ["NG-30"], 900, "2026-03-01"),
    ("F4a", "brightpay", "wrong_card_segment", "P4", ["BP-4"], 60, "2026-04-01"),
    ("F4b", "brightpay", "wrong_card_segment", "P4", ["BP-4"], 60, "2026-04-01"),
    ("F5", "brightpay", "stale_rate", "P5", ["BP-5"], 30, "2026-04-01"),
    ("F6", "brightpay", "refund_credit_missing", "R1", ["BP-6"], 50, "2026-04-01"),
    ("F7", "northgate", "fee_mismatch", "P9", ["NG-9"], 12, "2026-03-01"),
    ("F8", "brightpay", "rounding", "P11", ["BP-1"], 1, "2026-04-01"),
    ("F9", "brightpay", "rounding", "P12", ["BP-2"], 1, "2026-04-01"),
    ("F10", "northgate", "duplicate_charge", "P10", ["NG-10"], 70, "2026-03-01"),
]
CLEAN = [
    ("F1", "northgate", "stale_rate", "P1", ["NG-1"], 40, "2026-03-01"),
    ("F2", "northgate", "pass_through_above_reference", "P2", ["NG-2"], 25, "2026-03-01"),
    ("F3", "northgate", "retroactive_tier_not_applied", None, [], 900, "2026-03-01"),
    ("F4", "brightpay", "wrong_card_segment", "P4", ["BP-4"], 60, "2026-04-01"),
    ("F5", "brightpay", "fee_on_failed_attempt", "P5", ["BP-5"], 30, "2026-04-01"),
    ("F6", "brightpay", "refund_credit_missing", "R1", ["BP-6"], 50, "2026-04-01"),
    ("F8", "brightpay", "rounding", "P11", ["BP-1"], 1, "2026-04-01"),
]


def build(path, findings, client_findings=None):
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA truth; CREATE SCHEMA raw")
    con.execute("""CREATE TABLE truth.discrepancies (discrepancy_id VARCHAR, truth_id VARCHAR, provider VARCHAR,
        month VARCHAR, event_id VARCHAR, line_ids VARCHAR[], correct_minor BIGINT, billed_minor BIGINT,
        difference_minor BIGINT, currency VARCHAR)""")
    con.executemany("INSERT INTO truth.discrepancies VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'EUR')",
                    [(*d[:6], d[6], d[6]) for d in DISCREPANCIES])
    con.execute("""CREATE TABLE truth.client_leakage (truth_id VARCHAR, client_id VARCHAR, month VARCHAR,
        component VARCHAR, correct_minor BIGINT, billed_minor BIGINT, difference_minor BIGINT)""")
    con.execute("INSERT INTO truth.client_leakage VALUES ('L01', 'C1', '2026-03', 'payout_fees_sepa', 500, 0, -500)")
    con.execute("""CREATE TABLE truth.noise_events (truth_id VARCHAR, source_file VARCHAR, source_row BIGINT,
        line_id VARCHAR, event_id VARCHAR)""")
    con.executemany("INSERT INTO truth.noise_events VALUES (?, ?, ?, ?, ?)", NOISE)
    con.execute("""CREATE TABLE raw.fernway__client_invoice_lines AS SELECT * FROM (VALUES
        ('FW-2026-03-C1', '1', 'payment_fees'), ('FW-2026-03-C1', '3', 'payout_fees_sepa'))
        t(invoice_id, line_no, component)""")
    con.execute(f"CREATE TABLE main.fct_findings ({FINDING_COLS})")
    insert = """INSERT INTO {} (finding_id, party, counterparty, finding_type, event_id, line_ids,
        difference_minor, method, month) VALUES (?, ?, ?, ?, ?, ?, ?, 'rule', ?::DATE)"""
    con.executemany(insert.format("main.fct_findings"), [(f[0], "provider", *f[1:]) for f in findings])
    if client_findings is not None:
        con.execute(f"CREATE TABLE main.fct_client_billing_findings ({FINDING_COLS})")
        con.executemany(insert.format("main.fct_client_billing_findings"),
                        [(f[0], "client", *f[1:]) for f in client_findings])
    return con


def by_type(con):
    rows = con.execute("SELECT * FROM evaluation.detection_by_type").fetchall()
    names = [d[0] for d in con.description]
    return {r[0]: dict(zip(names, r)) for r in rows}


@pytest.fixture
def messy(tmp_path):
    con = build(tmp_path / "w.duckdb", MESSY)
    result = evaluate(con)
    yield con, result
    con.close()


def test_true_positive_and_wrong_type_on_right_line(messy):
    con, _ = messy
    d = by_type(con)
    # D01: F1 is a TP; F5 (stale_rate on the D08 line) is a false positive.
    assert (d["D01"]["found"], d["D01"]["findings"], d["D01"]["true_positives"]) == (1, 2, 1)
    assert d["D01"]["precision"] == 0.5 and d["D01"]["recall"] == 1.0
    # D08 missed: the only finding on its line has the wrong type.
    assert (d["D08"]["planted"], d["D08"]["found"], d["D08"]["recall"]) == (1, 0, 0.0)


def test_missed_planted_line(messy):
    d = by_type(messy[0])
    assert (d["D03"]["planted"], d["D03"]["found"], d["D03"]["findings"]) == (1, 0, 0)
    assert d["D03"]["recall"] == 0.0 and d["D03"]["precision"] == 1.0


def test_month_level_and_event_match(messy):
    d = by_type(messy[0])
    assert d["D02"]["found"] == 1 and d["D02"]["found_minor"] == 900
    assert d["D04"]["found"] == 1 and d["D04"]["precision"] == 1.0


def test_duplicate_finding_counts_once_for_recall_and_money(messy):
    d = by_type(messy[0])["D07"]
    assert (d["planted"], d["found"], d["findings"], d["true_positives"]) == (1, 1, 2, 2)
    assert d["recall"] == 1.0 and d["precision"] == 1.0
    assert (d["planted_minor"], d["found_minor"], d["money_recall"]) == (60, 60, 1.0)


def test_unmatched_false_positive(messy):
    con, _ = messy
    d = by_type(con)["D06"]
    assert (d["planted"], d["findings"], d["true_positives"], d["precision"]) == (0, 1, 0, 0.0)
    unexplained = dict(con.execute("SELECT finding_id, reason FROM evaluation.unexplained_findings").fetchall())
    assert unexplained == {"F5": "unmatched", "F7": "fee_mismatch", "F10": "unmatched"}


def test_noise_false_positive_and_rounding(messy):
    con, result = messy
    rows = con.execute("SELECT category, finding_id, noise_id FROM evaluation.noise_false_positives").fetchall()
    # F7 sits on an N01 row; F8 (rounding on N08) is fine; F9 is a rounding finding off N08 rows.
    assert sorted(rows) == [("noise", "F7", "N01"), ("rounding_off_n08", "F9", None)]
    assert (result.noise_fp, result.rounding_off_n08) == (1, 1)


def test_invoice_level_and_money_recall(messy):
    con, result = messy
    rows = con.execute("SELECT provider, month, planted_minor, findings_minor FROM evaluation.invoice_level").fetchall()
    assert rows == [("brightpay", "2026-04", 140, 200), ("northgate", "2026-03", 965, 1022)]
    assert result.money_recall == pytest.approx((40 + 900 + 60 + 50) / 1105)
    assert not result.client_evaluated and "L01" not in by_type(con)


def test_exit_codes(tmp_path, capsys):
    build(tmp_path / "messy.duckdb", MESSY).close()
    assert main(["--db", str(tmp_path / "messy.duckdb")]) == 1
    build(tmp_path / "clean.duckdb", CLEAN).close()
    assert main(["--db", str(tmp_path / "clean.duckdb")]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["--db", str(tmp_path / "missing.duckdb")]) == 2


def test_client_findings_via_invoice_lines(tmp_path):
    client = [("G1", "C1", "rail_not_billed", None, ["FW-2026-03-C1:3"], -500, "2026-03-01")]
    con = build(tmp_path / "c.duckdb", CLEAN, client)
    result = evaluate(con)
    assert result.client_evaluated and result.passed
    assert by_type(con)["L01"]["found"] == 1
    con.close()
    # The wrong component misses L01 and fails the run.
    wrong = [("G1", "C1", "rail_not_billed", None, ["FW-2026-03-C1:1"], -500, "2026-03-01")]
    build(tmp_path / "w.duckdb", CLEAN, wrong).close()
    assert main(["--db", str(tmp_path / "w.duckdb")]) == 1


def test_rerun_replaces_schema(messy):
    con, _ = messy
    evaluate(con)
    assert con.execute("SELECT count(*) FROM evaluation.detection_by_type").fetchone()[0] == 15
