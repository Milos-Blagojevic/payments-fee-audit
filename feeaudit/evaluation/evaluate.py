"""Builds the tables of schema `evaluation` (other tools add their own) from the findings tables and schema `truth`; see the package docstring."""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

# Pass/fail thresholds, the single place they are defined.
THRESHOLDS = {
    "min_precision": 0.98,  # per D type (and per L type when client findings exist)
    "min_recall": 0.98,  # per D type (and per L type when client findings exist)
    "min_money_recall": 0.99,  # total over every evaluated type
    "max_noise_false_positives": 0,  # non-rounding findings on noise rows
}

PROVIDER_FINDINGS = "main.fct_findings"
CLIENT_FINDINGS = "main.fct_client_billing_findings"
ANOMALIES = "main.fct_anomalies"

# truth id -> (finding_type, unit kind); data-contract section 5.
TYPE_MAP = {
    "D01": ("stale_rate", "line"),
    "D02": ("retroactive_tier_not_applied", "month"),
    "D03": ("pass_through_above_reference", "line"),
    "D04": ("refund_credit_missing", "event"),
    "D05": ("minimum_not_due", "month"),
    "D06": ("duplicate_charge", "line"),
    "D07": ("wrong_card_segment", "line"),
    "D08": ("fee_on_failed_attempt", "line"),
    "D09": ("chargeback_fee_mismatch", "line"),
    "D10": ("volume_discount_not_applied", "month"),
    "D11": ("fx_spread_above_cap", "line"),
    "D12": ("fx_rate_wrong_hour", "line"),
    "D13": ("payout_fee_cap_not_applied", "line"),
    "D14": ("unknown_charge", "line"),
    "D15": ("refund_fee_missing", "event"),
    "L01": ("rail_not_billed", "client"),
    "L02": ("promo_after_end_date", "client"),
    "L03": ("fx_markup_not_billed", "client"),
    "L04": ("volume_discount_too_high", "client"),
}


@dataclass
class Result:
    client_evaluated: bool
    detection: list[dict]
    money_recall: float
    noise_fp: int
    rounding_off_n08: int
    unexplained: int
    invoice_level: list[dict]
    anomalies: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def _exists(con, qualified: str) -> bool:
    schema, name = qualified.split(".")
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?", [schema, name]
    ).fetchone()[0] > 0


def _columns(con, qualified: str) -> set[str]:
    schema, name = qualified.split(".")
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ?", [schema, name]
    ).fetchall()
    return {r[0] for r in rows}


def _rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _prepare(con, client: bool) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE type_map (truth_id VARCHAR, finding_type VARCHAR, kind VARCHAR)")
    con.executemany("INSERT INTO type_map VALUES (?, ?, ?)", [(k, t, u) for k, (t, u) in TYPE_MAP.items()])

    # Only rule findings are scored: anomaly findings (method = 'anomaly') are reported in anomaly_report.
    rule_only = "WHERE method = 'rule'" if "method" in _columns(con, PROVIDER_FINDINGS) else ""
    provider = f"""
        SELECT finding_id, 'provider' AS party, counterparty, finding_type, event_id,
               coalesce(line_ids, []::VARCHAR[]) AS line_ids, difference_minor,
               strftime(month::DATE, '%Y-%m') AS month_key, []::VARCHAR[] AS components
        FROM {PROVIDER_FINDINGS} {rule_only}"""
    if client:
        if "component" in _columns(con, CLIENT_FINDINGS):
            comp = f"SELECT finding_id, [component] AS components FROM {CLIENT_FINDINGS} WHERE component IS NOT NULL"
        else:
            if _exists(con, "raw.fernway__client_invoice_lines"):
                line_map = "SELECT invoice_id || ':' || line_no AS ref, component FROM raw.fernway__client_invoice_lines"
            else:
                line_map = "SELECT NULL::VARCHAR AS ref, NULL::VARCHAR AS component WHERE false"
            comp = f"""
                SELECT e.finding_id, list(DISTINCT coalesce(m.component, e.ref)) AS components
                FROM (SELECT finding_id, unnest(line_ids) AS ref FROM {CLIENT_FINDINGS}) e
                LEFT JOIN ({line_map}) m ON m.ref = e.ref
                GROUP BY e.finding_id"""
        provider += f"""
        UNION ALL
        SELECT f.finding_id, 'client', f.counterparty, f.finding_type, f.event_id,
               coalesce(f.line_ids, []::VARCHAR[]), f.difference_minor,
               strftime(f.month::DATE, '%Y-%m'), coalesce(c.components, []::VARCHAR[])
        FROM {CLIENT_FINDINGS} f LEFT JOIN ({comp}) c USING (finding_id)"""
    con.execute(f"CREATE OR REPLACE TEMP TABLE f AS {provider}")

    client_units = """
        UNION ALL
        SELECT 'L:' || l.client_id || ':' || l.month || ':' || l.component, l.truth_id, t.finding_type, t.kind,
               'client', l.client_id, l.month, NULL, []::VARCHAR[], l.component, l.difference_minor
        FROM truth.client_leakage l JOIN type_map t USING (truth_id)""" if client else ""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE u AS
        SELECT d.discrepancy_id AS unit_id, d.truth_id, t.finding_type, t.kind, 'provider' AS party,
               d.provider AS counterparty, d.month, d.event_id, coalesce(d.line_ids, []::VARCHAR[]) AS line_ids,
               NULL::VARCHAR AS component, d.difference_minor
        FROM truth.discrepancies d JOIN type_map t USING (truth_id)
        {client_units}""")

    con.execute("""
        CREATE OR REPLACE TEMP TABLE m AS
        SELECT f.finding_id, u.unit_id
        FROM f JOIN u ON f.finding_type = u.finding_type AND f.party = u.party AND (
               (u.kind = 'line' AND list_has_any(f.line_ids, u.line_ids))
            OR (u.kind = 'event' AND f.event_id = u.event_id)
            OR (u.kind = 'month' AND f.counterparty = u.counterparty AND f.month_key = u.month)
            OR (u.kind = 'client' AND f.counterparty = u.counterparty AND f.month_key = u.month
                AND list_contains(f.components, u.component)))""")

    # Findings touching a noise row (by line id or event id).
    con.execute("""
        CREATE OR REPLACE TEMP TABLE fn AS
        SELECT f.finding_id, n.truth_id AS noise_id, n.line_id, n.event_id, n.source_file, n.source_row
        FROM f JOIN truth.noise_events n
          ON (n.line_id IS NOT NULL AND list_contains(f.line_ids, n.line_id))
          OR (n.event_id IS NOT NULL AND f.event_id = n.event_id)""")


def _build(con, client: bool) -> None:
    types = "" if client else "WHERE t.truth_id LIKE 'D%'"
    # Other tools also write into schema `evaluation`; replace only this module's tables.
    con.execute("CREATE SCHEMA IF NOT EXISTS evaluation")
    con.execute(f"""
        CREATE OR REPLACE TABLE evaluation.detection_by_type AS
        WITH first_match AS (  -- one finding per found unit, so duplicate findings do not double the money
            SELECT unit_id, min(finding_id) AS finding_id FROM m GROUP BY unit_id
        ),
        per_type AS (
            SELECT t.truth_id, t.finding_type,
                (SELECT count(*) FROM u WHERE u.truth_id = t.truth_id) AS planted,
                (SELECT count(DISTINCT m.unit_id) FROM m JOIN u USING (unit_id) WHERE u.truth_id = t.truth_id) AS found,
                (SELECT count(*) FROM f WHERE f.finding_type = t.finding_type) AS findings,
                (SELECT count(DISTINCT m.finding_id) FROM m JOIN f USING (finding_id)
                  WHERE f.finding_type = t.finding_type) AS true_positives,
                (SELECT coalesce(sum(difference_minor), 0) FROM u WHERE u.truth_id = t.truth_id)::BIGINT AS planted_minor,
                (SELECT coalesce(sum(f.difference_minor), 0) FROM f WHERE f.finding_id IN (
                    SELECT fm.finding_id FROM first_match fm JOIN u USING (unit_id) WHERE u.truth_id = t.truth_id
                ))::BIGINT AS found_minor
            FROM type_map t {types}
        )
        SELECT truth_id, finding_type, planted, found, findings, true_positives,
            CASE WHEN findings = 0 THEN 1.0 ELSE true_positives / findings END AS precision,
            CASE WHEN planted = 0 THEN 1.0 ELSE found / planted END AS recall,
            planted_minor, found_minor,
            CASE WHEN planted_minor = 0 THEN 1.0 ELSE abs(found_minor) / abs(planted_minor) END AS money_recall
        FROM per_type ORDER BY truth_id""")

    con.execute("""
        CREATE OR REPLACE TABLE evaluation.noise_false_positives AS
        SELECT 'noise' AS category, f.finding_id, f.party, f.finding_type, fn.noise_id,
               fn.line_id, fn.event_id, fn.source_file, fn.source_row, f.difference_minor
        FROM f JOIN fn USING (finding_id)
        WHERE f.finding_type <> 'rounding' AND f.finding_id NOT IN (SELECT finding_id FROM m)
        UNION ALL
        SELECT 'rounding_off_n08', f.finding_id, f.party, f.finding_type, NULL, NULL, NULL, NULL, NULL, f.difference_minor
        FROM f
        WHERE f.finding_type = 'rounding'
          AND f.finding_id NOT IN (SELECT finding_id FROM fn WHERE noise_id = 'N08')
        ORDER BY 1, 2""")

    con.execute("""
        CREATE OR REPLACE TABLE evaluation.invoice_level AS
        WITH fx AS (
            SELECT counterparty AS provider, month_key AS month, count(*) AS findings,
                   sum(difference_minor)::BIGINT AS findings_minor
            FROM f WHERE party = 'provider' AND finding_type <> 'rounding' GROUP BY ALL
        ), tx AS (
            SELECT provider, month, count(*) AS planted, sum(difference_minor)::BIGINT AS planted_minor
            FROM truth.discrepancies GROUP BY ALL
        )
        SELECT provider, month, coalesce(planted, 0) AS planted, coalesce(findings, 0) AS findings,
               coalesce(planted_minor, 0) AS planted_minor, coalesce(findings_minor, 0) AS findings_minor,
               coalesce(findings_minor, 0) - coalesce(planted_minor, 0) AS gap_minor
        FROM tx FULL OUTER JOIN fx USING (provider, month)
        ORDER BY provider, month""")

    con.execute("""
        CREATE OR REPLACE TABLE evaluation.unexplained_findings AS
        SELECT f.finding_id, f.party, f.counterparty, f.finding_type, f.month_key AS month, f.event_id, f.line_ids,
               f.difference_minor,
               CASE WHEN f.finding_type = 'fee_mismatch' THEN 'fee_mismatch' ELSE 'unmatched' END AS reason
        FROM f
        WHERE f.finding_type = 'fee_mismatch'
           OR (f.finding_type <> 'rounding'  -- rounding is reported in noise_false_positives
               AND f.finding_id NOT IN (SELECT finding_id FROM m)
               AND f.finding_id NOT IN (SELECT finding_id FROM fn))
        ORDER BY f.finding_id""")


def _anomaly_report(con) -> None:
    """Planted anomalies against fct_anomalies, reported only (no target).

    One row per planted anomaly (detected or not) and one per detected anomaly that matches no plant. A detection
    matches a plant when provider and component are equal, the card segments are equal or either is `all`, and the
    day is on or after the plant's start date.
    """
    if not (_exists(con, ANOMALIES) and _exists(con, "truth.anomalies")):
        con.execute("""
            CREATE OR REPLACE TABLE evaluation.anomaly_report (category VARCHAR, anomaly_id VARCHAR,
                provider VARCHAR, component VARCHAR, card_segment VARCHAR, line_type VARCHAR, rate_bps INTEGER,
                start_date DATE, planted_lines BIGINT,
                planted_minor BIGINT, detected BOOLEAN, first_detected_day DATE, days_to_detect INTEGER,
                detected_anomaly_id VARCHAR, anomaly_type VARCHAR, detections BIGINT, explained_by VARCHAR,
                is_finding BOOLEAN, explanation VARCHAR)""")
        return
    con.execute(f"""
        CREATE OR REPLACE TABLE evaluation.anomaly_report AS
        WITH pairs AS (
            SELECT t.anomaly_id AS planted_id, a.anomaly_id AS detected_id, a.day
            FROM truth.anomalies t JOIN {ANOMALIES} a
              ON a.provider = t.provider AND a.component = t.component AND a.day >= t.start_date
             AND (a.card_segment = t.card_segment OR 'all' IN (a.card_segment, t.card_segment))
        ), first_detection AS (
            SELECT planted_id, arg_min(detected_id, (day, detected_id)) AS detected_id, min(day) AS first_day,
                   count(*) AS detections
            FROM pairs GROUP BY planted_id
        )
        SELECT 'planted' AS category, t.anomaly_id, t.provider, t.component, t.card_segment, t.line_type, t.rate_bps,
               t.start_date,
               t.lines AS planted_lines, t.billed_minor AS planted_minor, fd.planted_id IS NOT NULL AS detected,
               fd.first_day AS first_detected_day, (fd.first_day - t.start_date)::INTEGER AS days_to_detect,
               a.anomaly_id AS detected_anomaly_id, a.anomaly_type, coalesce(fd.detections, 0) AS detections,
               a.explained_by, a.is_finding, a.explanation
        FROM truth.anomalies t
        LEFT JOIN first_detection fd ON fd.planted_id = t.anomaly_id
        LEFT JOIN {ANOMALIES} a ON a.anomaly_id = fd.detected_id
        UNION ALL
        SELECT 'not_planted', NULL, a.provider, a.component, a.card_segment, NULL, NULL, NULL, NULL, NULL, true, a.day,
               NULL,
               a.anomaly_id, a.anomaly_type, 1, a.explained_by, a.is_finding, a.explanation
        FROM {ANOMALIES} a
        WHERE a.anomaly_id NOT IN (SELECT detected_id FROM pairs)
        ORDER BY category DESC, anomaly_id, detected_anomaly_id""")


def evaluate(con: duckdb.DuckDBPyConnection) -> Result:
    """Build schema `evaluation` on `con` and return the metrics and the verdict."""
    if not _exists(con, PROVIDER_FINDINGS):
        raise RuntimeError(f"{PROVIDER_FINDINGS} not found; run `make build` first")
    client = _exists(con, CLIENT_FINDINGS)
    _prepare(con, client)
    _build(con, client)
    _anomaly_report(con)  # reported only: never a failure

    detection = _rows(con, "SELECT * FROM evaluation.detection_by_type ORDER BY truth_id")
    planted = sum(abs(r["planted_minor"]) for r in detection)
    found = sum(abs(r["found_minor"]) for r in detection)
    money_recall = 1.0 if planted == 0 else found / planted
    noise_fp, rounding_off = con.execute("""
        SELECT count(DISTINCT finding_id) FILTER (WHERE category = 'noise'),
               count(DISTINCT finding_id) FILTER (WHERE category = 'rounding_off_n08')
        FROM evaluation.noise_false_positives""").fetchone()
    unexplained = con.execute("SELECT count(*) FROM evaluation.unexplained_findings").fetchone()[0]
    result = Result(
        client_evaluated=client,
        detection=detection,
        money_recall=money_recall,
        noise_fp=noise_fp,
        rounding_off_n08=rounding_off,
        unexplained=unexplained,
        invoice_level=_rows(con, "SELECT * FROM evaluation.invoice_level"),
        anomalies=_rows(con, "SELECT * FROM evaluation.anomaly_report"),
    )
    for r in detection:
        if r["precision"] < THRESHOLDS["min_precision"]:
            result.failures.append(f"{r['truth_id']} precision {r['precision']:.3f} < {THRESHOLDS['min_precision']}")
        if r["recall"] < THRESHOLDS["min_recall"]:
            result.failures.append(f"{r['truth_id']} recall {r['recall']:.3f} < {THRESHOLDS['min_recall']}")
    if money_recall < THRESHOLDS["min_money_recall"]:
        result.failures.append(f"money recall {money_recall:.4f} < {THRESHOLDS['min_money_recall']}")
    if noise_fp > THRESHOLDS["max_noise_false_positives"]:
        result.failures.append(f"{noise_fp} noise false positives > {THRESHOLDS['max_noise_false_positives']}")
    return result
