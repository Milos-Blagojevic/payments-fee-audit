"""Client report: revenue leakage by client, type and month (M09) and margin per client
(M10), from `fct_client_billing_findings` and `fct_client_margin`."""

from collections import defaultdict

import duckdb

from feeaudit.reports.common import csv_text, eur, label, md_table, month, rate_pct, rows
from feeaudit.reports.finance import contract_names, truth_ids

MARGIN_SUMS = [
    "volume_minor", "billed_minor", "expected_minor", "revenue_leakage_minor", "event_provider_fees_minor",
    "volume_share_provider_fees_minor", "provider_fees_minor", "fx_spread_cost_minor", "provider_cost_minor",
    "margin_minor", "pending_provider_fees_minor",
]


def margin_by_client(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Whole-period sums of `fct_client_margin` per client."""
    return rows(
        con,
        f"select client_id, {', '.join(f'sum({c}) as {c}' for c in MARGIN_SUMS)}"
        " from main.fct_client_margin group by client_id order by client_id",
    )


def margin_totals(con: duckdb.DuckDBPyConnection) -> dict:
    total = rows(con, f"select {', '.join(f'sum({c}) as {c}' for c in MARGIN_SUMS)}, count(distinct client_id)"
                      " as clients, min(month) as first_month, max(month) as last_month from main.fct_client_margin")
    return total[0]


def leakage_by_type(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Client findings per type; `leakage_minor` is −difference over the under-billed findings."""
    ids = truth_ids(con)
    data = rows(
        con,
        """
        select finding_type, count(*) as findings, list_sort(list(distinct counterparty)) as clients,
            coalesce(-sum(difference_minor) filter (where difference_minor < 0), 0) as leakage_minor,
            coalesce(sum(difference_minor) filter (where difference_minor > 0), 0) as overbilled_minor
        from main.fct_client_billing_findings
        group by finding_type
        """,
    )
    for r in data:
        r["truth_id"] = ids.get(r["finding_type"], "")
    return sorted(data, key=lambda r: (r["truth_id"] or "~", r["finding_type"]))


def leakage_type_table(con: duckdb.DuckDBPyConnection) -> str:
    return md_table(
        ["Type", "Finding", "Clients", "Findings", "Billed too little", "Billed too much"],
        [[r["truth_id"], label(r["finding_type"]), f"{len(r['clients']):,}", f"{r['findings']:,}",
          eur(r["leakage_minor"]), eur(r["overbilled_minor"])] for r in leakage_by_type(con)],
        "llrrrr",
    )


def headline(con: duckdb.DuckDBPyConnection) -> str:
    t = margin_totals(con)
    findings = con.execute("select count(*) from main.fct_client_billing_findings").fetchone()[0]
    return (
        f"From {month(t['first_month'])} to {month(t['last_month'])}, Fernway billed its {t['clients']} clients "
        f"EUR {eur(t['billed_minor'])} against EUR {eur(t['expected_minor'])} due under their pricing agreements: "
        f"EUR {eur(t['revenue_leakage_minor'])} of revenue leakage (M09) across {findings:,} invoice lines. "
        f"After EUR {eur(t['provider_cost_minor'])} of provider fees and FX spread allocated to the clients' "
        f"events, the margin is EUR {eur(t['margin_minor'])} (M10), "
        f"{rate_pct(t['margin_minor'], t['volume_minor'])} of processed volume."
    )


def allocation_text(con: duckdb.DuckDBPyConnection) -> str:
    t = margin_totals(con)
    return (
        "Cost allocation (A09, A32): each provider fee goes to the client whose ledger event it belongs to "
        f"(EUR {eur(t['event_provider_fees_minor'])}); monthly provider charges without an event, minimums and "
        "volume adjustments, are split by the client's share of the volume the term is computed on "
        f"(EUR {eur(t['volume_share_provider_fees_minor'])}); the FX spread of the client's converted payouts (M08) "
        f"is a cost too (EUR {eur(t['fx_spread_cost_minor'])}). Fees on provider lines after the ledger watermark "
        f"(EUR {eur(t['pending_provider_fees_minor'])}) belong to the next billing cycle and are left out."
    )


def client_report(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    names = contract_names(con)
    findings = rows(
        con,
        """
        select counterparty as client_id, month, finding_type, direction, count(*) as findings,
            sum(difference_minor) as difference_minor
        from main.fct_client_billing_findings group by all order by all
        """,
    )
    margin = rows(con, "select * from main.fct_client_margin order by client_id, month")
    per_client = margin_by_client(con)

    by_client: dict[str, dict] = defaultdict(lambda: {"findings": 0, "leakage": 0, "over": 0, "types": set()})
    by_type_month: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in findings:
        c = by_client[r["client_id"]]
        c["findings"] += r["findings"]
        c["types"].add(r["finding_type"])
        if r["difference_minor"] < 0:
            c["leakage"] -= r["difference_minor"]
            by_type_month[r["finding_type"]][r["month"]] -= r["difference_minor"]
        else:
            c["over"] += r["difference_minor"]
    months = sorted({r["month"] for r in margin})
    ids = truth_ids(con)

    md = "\n\n".join([
        "# Client report",
        headline(con),
        "Amounts in EUR. *Leakage* is what the pricing agreement says Fernway should have billed minus what its "
        "invoice billed (positive = billed too little); findings are corrected on Fernway's own invoices, not "
        "disputed (A31). *Margin* is client billing minus the provider costs allocated to the client. "
        "Sources: `fct_client_billing_findings`, `fct_client_margin`; client × month rows are in "
        "`client_margin.csv`, findings by client, type and month in `client_findings.csv`.",
        allocation_text(con),
        "## Leakage by type",
        leakage_type_table(con),
        "## Leakage by month",
        md_table(
            ["Type", "Finding"] + [month(m) for m in months],
            [[ids.get(t, ""), label(t)] + [eur(values.get(m, 0)) for m in months]
             for t, values in sorted(by_type_month.items(), key=lambda i: (ids.get(i[0], "~"), i[0]))],
            "ll" + "r" * len(months),
        ),
        "## Leakage by client",
        "Clients with at least one finding.",
        md_table(
            ["Client", "Name", "Findings", "Billed too little", "Billed too much", "Types"],
            [[client, names.get(client, ""), f"{c['findings']:,}", eur(c["leakage"]), eur(c["over"]),
              ", ".join(sorted(ids.get(t) or t for t in c["types"]))] for client, c in sorted(by_client.items())],
            "llrrrl",
        ),
        "## Margin per client",
        "Whole period. *Event fees* are provider fees of the client's own events; *shared fees* its volume share "
        "of monthly charges; *FX spread* the M08 cost of its converted payouts.",
        md_table(
            ["Client", "Name", "Volume", "Billed", "Leakage", "Event fees", "Shared fees", "FX spread", "Margin",
             "Margin rate"],
            [[r["client_id"], names.get(r["client_id"], ""), eur(r["volume_minor"]), eur(r["billed_minor"]),
              eur(r["revenue_leakage_minor"]), eur(r["event_provider_fees_minor"]),
              eur(r["volume_share_provider_fees_minor"]), eur(r["fx_spread_cost_minor"]), eur(r["margin_minor"]),
              rate_pct(r["margin_minor"], r["volume_minor"])] for r in per_client],
            "llrrrrrrrr",
        ),
    ])
    margin_cols = ["client_id", "month"] + MARGIN_SUMS + ["margin_bps"]
    return {
        "client_report.md": md,
        "client_margin.csv": csv_text(
            margin_cols, [[month(r[c]) if c == "month" else r[c] for c in margin_cols] for r in margin]),
        "client_findings.csv": csv_text(
            ["client_id", "month", "finding_type", "direction", "findings", "difference_minor"],
            [[r["client_id"], month(r["month"]), r["finding_type"], r["direction"], r["findings"],
              r["difference_minor"]] for r in findings],
        ),
    }
