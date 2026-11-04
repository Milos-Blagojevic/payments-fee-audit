"""Follow one finding: one wrong-card-segment finding traced from the raw provider row to the
finding, every value read from the warehouse when the report is built."""

import json

import duckdb

from feeaudit.reference.terms import bps_of
from feeaudit.reports.common import as_of_date, eur, label, md_table, rows

FINDING_TYPE = "wrong_card_segment"

# provider → (raw table, staging model) of its line-level export.
PROVIDER_EXPORTS = {
    "northgate": ("raw.northgate__settlement_lines", "main.stg_northgate__settlement_lines"),
    "brightpay": ("raw.brightpay__transactions_export", "main.stg_brightpay__transactions_export"),
    "kestrel": ("raw.kestrel__payouts_statement", "main.stg_kestrel__payouts_statement"),
}
# ledger event type → (raw table, staging model, id column).
LEDGER = {
    "payment": ("raw.ledger__payments", "main.stg_ledger__payments", "payment_id"),
    "refund": ("raw.ledger__refunds", "main.stg_ledger__refunds", "refund_id"),
    "chargeback": ("raw.ledger__chargebacks", "main.stg_ledger__chargebacks", "chargeback_id"),
    "payout": ("raw.ledger__payouts", "main.stg_ledger__payouts", "payout_id"),
}


def choose(con: duckdb.DuckDBPyConnection) -> dict:
    """The first wrong-card-segment finding by month, event id and finding id."""
    found = rows(
        con,
        "select * from main.fct_findings where finding_type = ? and method = 'rule'"
        " order by month, event_id, finding_id limit 1",
        [FINDING_TYPE],
    )
    if not found:
        raise RuntimeError(f"no {FINDING_TYPE} finding to follow")
    return found[0]


def _one(con, sql: str, params: list) -> dict:
    found = rows(con, sql, params)
    if len(found) != 1:
        raise RuntimeError(f"expected one row, got {len(found)}: {sql} {params}")
    return found[0]


def _vertical(row: dict, keys: list[str] | None = None) -> str:
    keys = keys or [k for k in row if k not in ("source_file", "source_row")]
    return md_table(["Column", "Value"], [[f"`{k}`", "" if row[k] is None else f"`{row[k]}`"] for k in keys])


def trace(con: duckdb.DuckDBPyConnection) -> dict:
    """Every row on the path from the raw line to the finding."""
    finding = choose(con)
    line_id = finding["line_ids"][0]
    raw_table, stg_table = PROVIDER_EXPORTS[finding["counterparty"]]
    recon = _one(con, "select * from main.int_reconciliation where line_id = ?", [line_id])
    raw = _one(con, f"select * from {raw_table} where source_file = ? and source_row = ?",
               [recon["source_file"], recon["source_row"]])
    stg = _one(con, f"select * from {stg_table} where line_id = ?", [line_id])
    ledger_raw_table, ledger_stg_table, id_column = LEDGER[recon["event_type"]]
    ledger_stg = _one(con, f"select * from {ledger_stg_table} where {id_column} = ?", [finding["event_id"]])
    ledger_raw = _one(con, f"select * from {ledger_raw_table} where source_file = ? and source_row = ?",
                      [ledger_stg["source_file"], ledger_stg["source_row"]])
    line = _one(con, "select * from main.int_provider_lines where line_id = ? and component = ?",
                [line_id, finding["component"]])
    expected = _one(con, "select * from main.int_expected_charges where event_id = ? and component = ?",
                    [finding["event_id"], finding["component"]])
    comparison = _one(con, "select * from main.int_charge_comparison where event_id = ? and component = ?",
                      [finding["event_id"], finding["component"]])
    term = _one(con, "select * from main.dim_contract_terms where contract_term_id = ?",
                [f"{finding['contract_id']} v{finding['contract_version']} §{finding['clause']}"])
    return {"finding": finding, "line_id": line_id, "raw_table": raw_table, "stg_table": stg_table, "raw": raw,
            "stg": stg, "recon": recon, "ledger_raw_table": ledger_raw_table, "ledger_stg_table": ledger_stg_table,
            "ledger_raw": ledger_raw, "ledger_stg": ledger_stg, "line": line, "expected": expected,
            "comparison": comparison, "term": term}


def _segment_fees(t: dict) -> dict[str, int]:
    """The fee of this payment under every card segment of the blended-rate clause."""
    params = json.loads(t["term"]["parameters"])
    amount = t["expected"]["basis_minor"]
    mode = t["comparison"]["rounding_mode"]
    return {segment: bps_of(amount, p["bps"], mode) + p["fixed_minor"] for segment, p in params["segments"].items()}


def render(con: duckdb.DuckDBPyConnection) -> str:
    t = trace(con)
    f, recon, line, exp, term = t["finding"], t["recon"], t["line"], t["expected"], t["term"]
    segment_fees = _segment_fees(t)
    billed_as = sorted(s for s, fee in segment_fees.items() if fee == f["billed_minor"])
    params = json.loads(term["parameters"])["segments"]
    if billed_as:
        p = params[billed_as[0]]
        billed_reading = (
            f"The amount billed, {eur(f['billed_minor'])}, is exactly the fee at the `{billed_as[0]}` segment rate: "
            f"{eur(exp['basis_minor'])} × {p['bps'] / 100:.2f}% + {eur(p['fixed_minor'])}, rounded "
            f"{t['comparison']['rounding_mode'].replace('_', ' ')}, = {eur(segment_fees[billed_as[0]])}. "
            f"The provider priced the card (segment `{exp['card_segment']}`) at the `{billed_as[0]}` rate."
        )
    else:
        billed_reading = (f"The amount billed, {eur(f['billed_minor'])}, matches no segment rate of the clause "
                          f"({', '.join(f'{s}: {eur(v)}' for s, v in sorted(segment_fees.items()))}).")

    raw_file_line = t["raw"]["source_row"] + 1  # data rows are 1-based after the header line
    parts = [
        "# Follow one finding",
        f"One finding of type `{f['finding_type']}` ({label(f['finding_type'])}), followed from the provider's "
        "raw file to the finding. It is the first finding of that type by month and event id. Every value below "
        "is read from `warehouse/fees.duckdb` when the report is built (`python -m feeaudit.reports`). "
        "Money is in minor units (cents) in the tables and in EUR in the text.",
        "## 1. The raw file row",
        f"Line `{t['line_id']}` is data row {t['raw']['source_row']} (file line {raw_file_line}, after the header) "
        f"of `{t['raw']['source_file']}`, loaded verbatim as text into `{t['raw_table']}`:",
        _vertical(t["raw"]),
        f"The ledger event it refers to is data row {t['ledger_raw']['source_row']} of "
        f"`{t['ledger_raw']['source_file']}` (`{t['ledger_raw_table']}`):",
        _vertical(t["ledger_raw"]),
        "## 2. The staging rows",
        f"`{t['stg_table'].removeprefix('main.')}` types and cleans the provider row (labels, units, UTC time):",
        _vertical(t["stg"]),
        f"`{t['ledger_stg_table'].removeprefix('main.')}` does the same for the ledger event:",
        _vertical(t["ledger_stg"]),
        "## 3. The reconciliation match",
        f"`int_reconciliation` matches the line to ledger event `{recon['event_id']}` by "
        f"`{recon['match_method']}` with status `{recon['status']}`. `int_provider_lines` splits the line into fee "
        f"components; the `{line['component']}` component is billed at {line['amount_minor']} cents and the card "
        f"is in segment `{line['billed_card_segment']}` "
        f"({line['card_type']}, {line['card_region']}).",
        _vertical(recon, ["line_id", "event_id", "event_type", "match_slot", "match_method", "status",
                          "statement_month"]),
        "## 4. The expected charge",
        f"The contract in force on {exp['event_timestamp_utc']:%Y-%m-%d} is {exp['contract_id']} version "
        f"{exp['contract_version']}. Clause {exp['clause']}, *{term['title']}*: {term['clause_text']}",
        f"`int_expected_charges` applies it to the payment: **{exp['formula']}**, "
        f"so {exp['expected_minor']} cents are due.",
        _vertical(exp, ["expected_charge_id", "basis_minor", "card_segment", "rate_bps", "expected_minor",
                        "formula"]),
        "## 5. The finding",
        f"`int_charge_comparison` puts the billed and the expected amount side by side: billed "
        f"{t['comparison']['billed_minor']}, expected {t['comparison']['expected_minor']}, difference "
        f"{t['comparison']['difference_minor']} cents, classified `{t['comparison']['finding_type']}`.",
        billed_reading,
        f"`fct_findings` records it as an overcharge of EUR {eur(f['difference_minor'])} on invoice "
        f"{f['invoice_id']} (dated {f['invoice_date']}); the dispute deadline is {f['dispute_deadline']}, "
        f"{abs(f['days_left'])} days {'after' if f['days_left'] >= 0 else 'before'} the reference date {as_of_date()} (A22).",
        _vertical(f, ["finding_id", "finding_type", "counterparty", "month", "event_id", "line_ids", "component",
                      "clause", "expected_minor", "billed_minor", "difference_minor", "direction", "invoice_id",
                      "dispute_deadline", "evidence"]),
    ]
    return "\n\n".join(parts)
