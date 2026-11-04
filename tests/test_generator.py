"""Generator checks: determinism, calibration, zero-rate billing, invoice totals, planting rules, anomalies."""

import collections
import copy
import hashlib
from pathlib import Path

import duckdb
import numpy as np
import pytest

from feeaudit.load import load
from generator.calibration import in_range, metrics
from generator.client_agreements import render_all
from generator.common import load_config, round_div
from generator.ledger import watermark
from generator.run import REPO, generate

CONFIG = REPO / "config/generator.yml"


def small_config(zero_rates=False):
    """A quick world: fewer events, and no month-level plants (their volume conditions need the full world)."""
    cfg = load_config(CONFIG)
    cfg["payments"]["attempts"] = 30000
    cfg["payouts"]["count"] = 4000
    cfg["payouts"]["large_swift"]["share"] = 0.1
    d = cfg["discrepancies"]
    for code in ("D02", "D05", "D10"):
        d[code]["months"] = []
    if zero_rates:
        for code, spec in d.items():
            for key in spec:
                if key in ("share", "share_of_commercial"):
                    spec[key] = 0.0
        d["D14"] = {"northgate_events": 0, "brightpay_events": 0}
        for spec in cfg["anomalies"].values():
            spec["enabled"] = False
    return cfg


@pytest.fixture(scope="session")
def default_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("default")
    g = generate(load_config(CONFIG), out)
    db = out / "fees.duckdb"
    load(out / "data", db)
    return g, out, db


@pytest.fixture(scope="session")
def default_db(default_run):
    with duckdb.connect(str(default_run[2]), read_only=True) as con:
        yield con


def table_checksums(data_dir):
    """Row count and sha256 per source table directory (raw) or truth file."""
    out = {}
    for path in sorted(Path(data_dir).rglob("*.csv")):
        key = path.parent.relative_to(data_dir).as_posix() if "raw" in path.parts else path.stem
        h, n = out.get(key, (hashlib.sha256(), 0))
        content = path.read_bytes()
        h.update(path.name.encode() + content)
        out[key] = (h, n + max(content.count(b"\n") - 1, 0))
    return {k: (n, h.hexdigest()) for k, (h, n) in out.items()}


def test_same_seed_same_output(tmp_path):
    cfg = small_config()
    generate(cfg, tmp_path / "a")
    generate(copy.deepcopy(cfg), tmp_path / "b")
    a, b = table_checksums(tmp_path / "a/data"), table_checksums(tmp_path / "b/data")
    assert len(a) >= 19
    assert a == b
    cfg["seed"] += 1
    generate(cfg, tmp_path / "c")
    assert table_checksums(tmp_path / "c/data") != a


def test_calibration_targets_in_range(default_run):
    out = [(name, shown, rng) for name, value, low, high, shown, rng in metrics(default_run[0]) if not in_range(value, low, high)]
    assert out == []


def test_zero_rates_bill_exactly_the_correct_charges(tmp_path):
    g = generate(small_config(zero_rates=True), tmp_path)
    assert g["truth"] == [] and g["anomalies"] == []
    ng, bp, ks = g["northgate"], g["brightpay"], g["kestrel"]
    assert (ng["billed"] == ng["correct"]).all()
    assert (ks["fee_billed"] == ks["fee_correct"]).all()
    assert (ks["debit_billed"] == ks["debit_correct"]).all()
    assert (ks["rate_hour"] == ks["executed"] // 3600).all()
    # Brightpay differs only on N08 rows: one minor unit, the half-up result of a half-even tie.
    n08 = {r[3] for r in g["noise"] if r[0] == "N08"}
    diff = np.flatnonzero(bp["billed"] != bp["correct"])
    assert len(diff) == len(n08) > 0
    assert (bp["billed"][diff] - bp["correct"][diff] == 1).all()
    assert (ng["exported"] | (ng["correct"] == 0)).all()
    assert (bp["exported"] | (bp["correct"] == 0)).all()


def _parse_major(column):
    return f"CAST(round(CAST(replace({column}, ',', '.') AS DECIMAL(18, 2)) * 100) AS BIGINT)"


def test_invoice_totals_equal_statement_lines(default_db):
    con = default_db
    month = r"regexp_extract(source_file, '(\d{4}-\d{2})\.csv$', 1)"
    checks = {
        "northgate": f"""
            SELECT i.period, {_parse_major('i.total_amount')} AS invoiced, s.total FROM raw.northgate__invoices i
            JOIN (SELECT m, sum(fee) AS total FROM (SELECT DISTINCT line_ref, {month} AS m, {_parse_major('fee_amount')} AS fee
                  FROM raw.northgate__settlement_lines) GROUP BY m) s ON s.m = i.period""",
        "brightpay": f"""
            SELECT i.billing_month, CAST(i.total AS BIGINT), s.total + coalesce(a.total, 0) FROM raw.brightpay__invoices i
            JOIN (SELECT m, sum(fee) AS total FROM (SELECT DISTINCT id, {month} AS m, CAST(fee AS BIGINT) AS fee
                  FROM raw.brightpay__transactions_export) GROUP BY m) s ON s.m = i.billing_month
            LEFT JOIN (SELECT period, sum(CAST(amount AS BIGINT)) AS total FROM raw.brightpay__adjustments GROUP BY 1) a
              ON a.period = i.billing_month""",
        "kestrel": f"""
            SELECT i.statement_month, {_parse_major('i.amount_eur')}, s.total FROM raw.kestrel__invoices i
            JOIN (SELECT {month} AS m, sum({_parse_major('fee_eur')}) AS total FROM raw.kestrel__payouts_statement GROUP BY 1) s
              ON s.m = i.statement_month""",
        "fernway": """
            SELECT i.invoice_id, CAST(i.total_minor AS BIGINT), sum(CAST(l.amount_minor AS BIGINT))
            FROM raw.fernway__client_invoices i JOIN raw.fernway__client_invoice_lines l USING (invoice_id)
            GROUP BY ALL""",
    }
    for name, sql in checks.items():
        rows = con.execute(sql).fetchall()
        assert len(rows) >= 6, name
        assert [r for r in rows if r[1] != r[2]] == [], name


def test_noise_rows_point_at_their_lines(default_db):
    con = default_db
    for table, id_col in (("northgate__settlement_lines", "line_ref"), ("brightpay__transactions_export", "id"),
                          ("kestrel__payouts_statement", "statement_line_id")):
        mismatched = con.execute(f"""
            SELECT count(*) FROM truth.noise_events n JOIN raw.{table} r USING (source_file, source_row)
            WHERE r.{id_col} <> n.line_id""").fetchone()[0]
        assert mismatched == 0
    missing = con.execute("""
        SELECT count(*) FROM truth.noise_events n WHERE source_row IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM raw.northgate__settlement_lines r WHERE r.source_file = n.source_file AND r.source_row = n.source_row
          UNION ALL SELECT 1 FROM raw.brightpay__transactions_export r WHERE r.source_file = n.source_file AND r.source_row = n.source_row
          UNION ALL SELECT 1 FROM raw.kestrel__payouts_statement r WHERE r.source_file = n.source_file AND r.source_row = n.source_row)
    """).fetchone()[0]
    assert missing == 0
    n06 = con.execute("""
        SELECT count(*) FROM truth.noise_events n JOIN raw.northgate__settlement_lines r USING (source_file, source_row)
        WHERE n.truth_id = 'N06' AND r.txn_ref IS NOT NULL""").fetchone()[0]
    assert n06 == 0


def test_planting_rules(default_run, default_db):
    g = default_run[0]
    cfg = g["cfg"]
    con = default_db
    # At most one discrepancy per provider line.
    dup = con.execute("""SELECT count(*) - count(DISTINCT l) FROM (SELECT unnest(line_ids) AS l FROM truth.discrepancies
                         WHERE truth_id NOT IN ('D04'))""").fetchone()[0]
    assert dup == 0
    # No discrepancy on events in the ledger lag window, and no month-level plant in the last month.
    last = g["months"][-1]
    assert not [r for r in g["truth"] if r[0] in ("D02", "D05", "D10") and r[2] == last]
    in_ledger = {r[0] for r in con.execute("""
        SELECT payment_id FROM raw.ledger__payments UNION ALL SELECT refund_id FROM raw.ledger__refunds
        UNION ALL SELECT chargeback_id FROM raw.ledger__chargebacks UNION ALL SELECT payout_id FROM raw.ledger__payouts""").fetchall()}
    for code, _, _, event_id, *_ in g["truth"]:
        if event_id:
            assert (event_id in in_ledger) == (code != "D14"), (code, event_id)
    # D02 is not planted in the month of D01.
    d01 = {r[2] for r in g["truth"] if r[0] == "D01"}
    assert d01 and not d01 & {r[2] for r in g["truth"] if r[0] == "D02"}
    # Every discrepancy is at least one minor unit; D15 is the only undercharge.
    assert all(r[6] != r[5] for r in g["truth"])
    assert {r[0] for r in g["truth"] if r[6] < r[5]} == {"D15"}
    # The ledger stops at the watermark: no file for the day after the period.
    created = con.execute("SELECT max(created_at) FROM raw.ledger__payments").fetchone()[0]
    assert np.datetime64(created.rstrip("Z"), "s").astype(np.int64) < watermark(cfg)


def test_ledger_files_hold_the_previous_day(default_db):
    bad = default_db.execute(r"""
        SELECT count(*) FROM raw.ledger__payments
        WHERE CAST(regexp_extract(source_file, '(\d{4}-\d{2}-\d{2})\.csv$', 1) AS DATE) - 1 <> CAST(left(created_at, 10) AS DATE)
    """).fetchone()[0]
    assert bad == 0


def test_planted_anomaly(default_run, default_db):
    g = default_run[0]
    con = default_db
    spec = g["cfg"]["anomalies"]["X01"]
    (row,) = con.execute("SELECT * FROM truth.anomalies").fetchall()
    truth = dict(zip([d[0] for d in con.description], row))
    assert (truth["anomaly_id"], truth["provider"], truth["line_type"], truth["component"]) == (
        "X01", "northgate", spec["line_type"], spec["line_type"].lower())
    lines, first_local_day, billed = con.execute(f"""
        SELECT count(*), min(left(txn_time, 10)),
               sum(CAST(round(CAST(replace(fee_amount, ',', '.') AS DECIMAL(18, 2)) * 100) AS BIGINT))
        FROM (SELECT DISTINCT line_ref, txn_time, fee_amount FROM raw.northgate__settlement_lines
              WHERE line_type = '{spec["line_type"]}')""").fetchone()
    assert lines == truth["lines"] > 0 and billed == truth["billed_minor"]
    assert first_local_day >= str(spec["start"])  # Berlin local time is never before the UTC start date
    # Only on succeeded Northgate payments from the start date (those after the ledger watermark are not in the
    # ledger yet), never on a D14 payment.
    bad = con.execute(f"""
        SELECT count(*) FROM raw.northgate__settlement_lines s
        JOIN raw.ledger__payments p ON p.payment_id = s.txn_ref
        WHERE s.line_type = '{spec["line_type"]}'
          AND (p.status <> 'succeeded' OR p.provider <> 'northgate' OR p.created_at < '{spec["start"]}')""").fetchone()[0]
    assert bad == 0
    refs = {r[0] for r in con.execute(f"""
        SELECT txn_ref FROM raw.northgate__settlement_lines WHERE line_type = '{spec["line_type"]}'""").fetchall()}
    assert not refs & {r[3] for r in g["truth"] if r[0] == "D14"}


def test_anomaly_leaves_every_plant_unchanged(tmp_path):
    """D and L planting are identical with the anomaly off; noise only gains rows on the anomaly lines."""
    cfg = small_config()
    off_cfg = copy.deepcopy(cfg)
    for spec in off_cfg["anomalies"].values():
        spec["enabled"] = False
    on, off = generate(cfg, tmp_path / "on"), generate(off_cfg, tmp_path / "off")
    assert on["anomalies"] and on["anomalies"][0][7] > 0 and not off["anomalies"]

    def plants(g):
        return sorted((code, p, month, ev, correct, billed) for code, p, month, ev, _, correct, billed in g["truth"])

    assert plants(on) == plants(off)
    assert on["clients"]["leakage"] == off["clients"]["leakage"]
    noise_on = collections.Counter((t, ev) for t, _, _, _, ev in on["noise"])
    noise_off = collections.Counter((t, ev) for t, _, _, _, ev in off["noise"])
    assert not noise_off - noise_on
    assert {t for t, _ in noise_on - noise_off} == {"N04", "N06", "N07"}


def test_committed_client_agreements_equal_fresh_render():
    rendered = render_all(load_config(CONFIG))
    directory = REPO / "contracts/clients"
    committed = {p.name: p.read_text() for p in directory.glob("*.yml")}
    assert sorted(committed) == sorted(rendered)
    assert [name for name in rendered if committed[name] != rendered[name]] == []


def test_generator_rounding():
    values = np.array([5, 15, 25, -5, -15, 4, 6])
    assert round_div(values, 10, "half_even").tolist() == [0, 2, 2, 0, -2, 0, 1]
    assert round_div(values, 10, "half_up").tolist() == [1, 2, 3, -1, -2, 0, 1]
