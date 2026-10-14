"""Finance outputs (spec section 13, items 1–4): each function returns {relative path: file text}."""

import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal

import duckdb

from feeaudit.reports.common import csv_text, eur, label, md_table, month, pct_change, rate_pct, rows

CARD_SEGMENTS = ("eea_consumer", "other")

# Rule findings that are disputed: overcharges, never rounding (fct_dispute_queue).
DISPUTED = "method = 'rule' and finding_type <> 'rounding' and difference_minor > 0"
QUEUE_KEY = "coalesce(invoice_id, counterparty || ':' || strftime(statement_month, '%Y-%m'))"

PACK_COLUMNS = [
    "finding_id", "finding_type", "month", "event_id", "line_ids", "component", "contract_id", "contract_version",
    "clause", "expected_minor", "billed_minor", "difference_minor", "currency", "formula", "evidence",
    "invoice_id", "dispute_deadline",
]


def _previous_month(value: dt.date) -> dt.date:
    return (value - dt.timedelta(days=1)).replace(day=1)


def _bps(numerator: int, volume: int | None) -> Decimal | None:
    if not volume:
        return None
    return (Decimal(numerator * 10000) / Decimal(volume)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _bps_change(current: Decimal | None, previous: Decimal | None) -> str:
    if current is None or previous is None:
        return ""
    return f"{current - previous:+} bp"


def truth_ids(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """finding_type → planted type id (D01…), from schema `evaluation`."""
    return dict(con.execute("select finding_type, truth_id from evaluation.detection_by_type").fetchall())


def contract_names(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(con.execute("select distinct counterparty, contract_name from main.dim_contract_terms").fetchall())


# 1. Monthly provider cost report ------------------------------------------------------------------------------


def provider_costs(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    data = rows(con, "select * from main.fct_provider_costs order by provider, month, component, card_segment")
    by_key = {(r["provider"], r["month"], r["component"], r["card_segment"]): r for r in data}
    names = contract_names(con)

    csv_rows = []
    for r in data:
        prev = by_key.get((r["provider"], _previous_month(r["month"]), r["component"], r["card_segment"]))
        prev_billed = prev["billed_minor"] if prev else None
        csv_rows.append([
            r["provider"], month(r["month"]), r["component"], r["card_segment"], r["lines"], r["volume_minor"],
            r["billed_minor"], r["pending_billed_minor"], r["expected_minor"], r["difference_minor"],
            r["effective_rate_bps"], prev_billed, None if prev_billed is None else r["billed_minor"] - prev_billed,
        ])
    csv_out = csv_text(
        ["provider", "month", "component", "card_segment", "lines", "volume_minor", "billed_minor",
         "pending_billed_minor", "expected_minor", "difference_minor", "effective_rate_bps",
         "previous_month_billed_minor", "change_billed_minor"],
        csv_rows,
    )

    # Provider × month totals; the volume is the sum of the card segments' volumes (M01).
    totals: dict[tuple, dict] = defaultdict(lambda: {"lines": 0, "billed": 0, "expected": 0, "difference": 0,
                                                       "pending": 0, "volume": {}})
    segments: dict[tuple, dict] = defaultdict(lambda: {"billed": 0, "markup": None, "volume": None})
    components: dict[tuple, dict] = defaultdict(dict)
    for r in data:
        t = totals[(r["provider"], r["month"])]
        t["lines"] += r["lines"]
        t["billed"] += r["billed_minor"]
        t["expected"] += r["expected_minor"]
        t["difference"] += r["difference_minor"]
        t["pending"] += r["pending_billed_minor"]
        if r["card_segment"] in CARD_SEGMENTS:
            t["volume"][r["card_segment"]] = r["volume_minor"]
            s = segments[(r["provider"], r["card_segment"], r["month"])]
            s["billed"] += r["billed_minor"]
            s["volume"] = r["volume_minor"]
            if r["component"] == "markup":
                s["markup"] = r["billed_minor"]
        c = components[(r["provider"], r["component"])]
        c[r["month"]] = c.get(r["month"], 0) + r["billed_minor"]

    months = sorted({r["month"] for r in data})
    total_rows = []
    for (provider, m), t in sorted(totals.items()):
        volume = sum(t["volume"].values()) or None
        prev = totals.get((provider, _previous_month(m)))
        prev_volume = (sum(prev["volume"].values()) or None) if prev else None
        total_rows.append([
            names.get(provider, provider), month(m), eur(volume), f"{t['lines']:,}", eur(t["billed"]),
            eur(t["pending"]), eur(t["difference"]), rate_pct(t["billed"], volume),
            pct_change(t["billed"], prev["billed"] if prev else None),
            _bps_change(_bps(t["billed"], volume), _bps(prev["billed"], prev_volume) if prev else None),
        ])
    segment_rows = []
    for (provider, segment, m), s in sorted(segments.items()):
        prev = segments.get((provider, segment, _previous_month(m)))
        segment_rows.append([
            names.get(provider, provider), segment, month(m), eur(s["volume"]), eur(s["billed"]),
            rate_pct(s["billed"], s["volume"]), rate_pct(s["markup"], s["volume"]),
            pct_change(s["billed"], prev["billed"] if prev else None),
            _bps_change(_bps(s["billed"], s["volume"]), _bps(prev["billed"], prev["volume"]) if prev else None),
        ])
    component_rows = [
        [names.get(provider, provider), component] + [eur(values.get(m, 0)) for m in months]
        for (provider, component), values in sorted(components.items())
    ]

    md = "\n\n".join([
        "# Monthly provider cost report",
        "Fees billed by each provider, by UTC month of the event, against the processed card volume. "
        "Amounts in EUR. *Effective rate* is fees billed ÷ processed volume; *markup rate* is the acquirer markup "
        "÷ volume (Northgate only; Brightpay bills one blended fee). *Difference* is billed − expected on the "
        "charges that could be checked; *pending* is billed but not checkable yet (ledger lag). Changes compare "
        "with the previous month. Kestrel bills payouts, so it has no card volume. Source: `fct_provider_costs`; "
        "every component and segment row is in `provider_costs.csv`.",
        "## Totals by provider and month",
        md_table(
            ["Provider", "Month", "Card volume", "Lines", "Fees billed", "Pending", "Difference", "Effective rate",
             "Fees vs prev. month", "Rate vs prev. month"],
            total_rows, "llrrrrrrrr",
        ),
        "## By card segment",
        "Payment, refund and chargeback fees whose payment has a known card segment.",
        md_table(
            ["Provider", "Segment", "Month", "Volume", "Fees billed", "Effective rate", "Markup rate",
             "Fees vs prev. month", "Rate vs prev. month"],
            segment_rows, "lllrrrrrr",
        ),
        "## Fees by component",
        md_table(["Provider", "Component"] + [month(m) for m in months], component_rows, "ll" + "r" * len(months)),
    ])
    return {"provider_costs.md": md, "provider_costs.csv": csv_out}


# 2. Findings summary ------------------------------------------------------------------------------------------


def findings_overview(con: duckdb.DuckDBPyConnection) -> dict:
    """Headline numbers shared by the findings summary and the README."""
    over, under, count, rounding_count, rounding_minor = con.execute(
        f"""
        select
            coalesce(sum(difference_minor) filter (where {DISPUTED}), 0),
            coalesce(sum(difference_minor) filter (where method = 'rule' and finding_type <> 'rounding'
                and difference_minor < 0), 0),
            count(*) filter (where method = 'rule' and finding_type <> 'rounding'),
            count(*) filter (where finding_type = 'rounding'),
            coalesce(sum(difference_minor) filter (where finding_type = 'rounding'), 0)
        from main.fct_findings
        """
    ).fetchone()
    recoverable, disputed, open_invoices, expired_invoices = con.execute(
        "select sum(recoverable_minor), sum(overcharge_minor), count(*) filter (where status = 'open'),"
        " count(*) filter (where status = 'expired') from main.fct_dispute_queue where overcharge_findings > 0"
    ).fetchone()
    first, last = con.execute("select min(month), max(month) from main.fct_findings").fetchone()
    return {
        "overcharge_minor": over, "undercharge_minor": under, "findings": count,
        "rounding_findings": rounding_count, "rounding_minor": rounding_minor,
        "recoverable_minor": recoverable, "past_deadline_minor": disputed - recoverable,
        "open_invoices": open_invoices, "expired_invoices": expired_invoices,
        "first_month": month(first), "last_month": month(last),
    }


def findings_by_type(con: duckdb.DuckDBPyConnection) -> list[dict]:
    ids = truth_ids(con)
    data = rows(
        con,
        """
        select finding_type, count(*) as findings,
            coalesce(sum(difference_minor) filter (where difference_minor > 0), 0) as over_minor,
            coalesce(sum(difference_minor) filter (where difference_minor < 0), 0) as under_minor,
            list_sort(list(distinct counterparty)) as providers
        from main.fct_findings
        where method = 'rule' and finding_type <> 'rounding'
        group by finding_type
        """,
    )
    for r in data:
        r["truth_id"] = ids.get(r["finding_type"], "")
    return sorted(data, key=lambda r: (r["truth_id"] or "~", r["finding_type"]))


def findings_type_table(con: duckdb.DuckDBPyConnection) -> str:
    names = contract_names(con)
    return md_table(
        ["Type", "Finding", "Provider", "Findings", "Overcharge", "Undercharge"],
        [
            [r["truth_id"], label(r["finding_type"]), ", ".join(names.get(p, p) for p in r["providers"]),
             f"{r['findings']:,}", eur(r["over_minor"]), eur(r["under_minor"])]
            for r in findings_by_type(con)
        ],
        "lllrrr",
    )


def findings_headline(con: duckdb.DuckDBPyConnection, as_of: str) -> str:
    o = findings_overview(con)
    return (
        f"From {o['first_month']} to {o['last_month']}, {o['findings']:,} provider charges differ from the contracts: "
        f"EUR {eur(o['overcharge_minor'])} overcharged and EUR {eur(-o['undercharge_minor'])} undercharged. "
        f"As of {as_of}, EUR {eur(o['recoverable_minor'])} can still be disputed on {o['open_invoices']} open "
        f"invoices (M07); EUR {eur(o['past_deadline_minor'])} is past its dispute deadline. "
        f"A further {o['rounding_findings']:,} one-cent rounding differences (EUR {eur(o['rounding_minor'])} net) "
        f"are reported but not disputed."
    )


def findings_summary(con: duckdb.DuckDBPyConnection, as_of: str) -> dict[str, str]:
    names = contract_names(con)
    by_provider = rows(
        con,
        f"""
        with f as (select * from main.fct_findings where method = 'rule' and finding_type <> 'rounding'),
        q as (select provider, sum(recoverable_minor) as recoverable_minor from main.fct_dispute_queue group by 1)
        select counterparty as provider, count(*) as findings,
            coalesce(sum(difference_minor) filter (where difference_minor > 0), 0) as over_minor,
            coalesce(sum(difference_minor) filter (where difference_minor < 0), 0) as under_minor,
            any_value(q.recoverable_minor) as recoverable_minor
        from f left join q on q.provider = f.counterparty
        group by 1 order by 1
        """,
    )
    by_month = rows(
        con,
        """
        select counterparty as provider, month,
            coalesce(sum(difference_minor) filter (where difference_minor > 0), 0) as over_minor,
            coalesce(sum(difference_minor) filter (where difference_minor < 0), 0) as under_minor
        from main.fct_findings where method = 'rule' and finding_type <> 'rounding'
        group by all order by all
        """,
    )
    queue = rows(con, "select * from main.fct_dispute_queue order by provider, statement_month, dispute_queue_id")
    detail = rows(
        con,
        """
        select counterparty as provider, strftime(month, '%Y-%m') as month, finding_type, direction,
            count(*) as findings, sum(difference_minor) as difference_minor
        from main.fct_findings where method = 'rule'
        group by all order by all
        """,
    )

    months = sorted({r["month"] for r in by_month})
    matrix: dict[str, dict] = defaultdict(dict)
    for r in by_month:
        matrix[r["provider"]][r["month"]] = r
    month_rows = []
    for provider in sorted(matrix):
        month_rows.append([names.get(provider, provider), "overcharge"]
                          + [eur(matrix[provider].get(m, {}).get("over_minor", 0)) for m in months])
        if any(r["under_minor"] for r in matrix[provider].values()):
            month_rows.append([names.get(provider, provider), "undercharge"]
                              + [eur(matrix[provider].get(m, {}).get("under_minor", 0)) for m in months])

    md = "\n\n".join([
        "# Findings summary",
        findings_headline(con, as_of),
        "Amounts in EUR. An overcharge is billed above what the contract allows; an undercharge is billed below it "
        "(reported, never disputed). Recoverable means the invoice's dispute deadline is on or after "
        f"{as_of}. Sources: `fct_findings`, `fct_dispute_queue`; the breakdown by provider, month and type is in "
        "`findings_summary.csv`.",
        "## By type",
        findings_type_table(con),
        "## By provider",
        md_table(
            ["Provider", "Findings", "Overcharge", "Undercharge", "Recoverable now", "Past deadline"],
            [[names.get(r["provider"], r["provider"]), f"{r['findings']:,}", eur(r["over_minor"]),
              eur(r["under_minor"]), eur(r["recoverable_minor"]), eur(r["over_minor"] - r["recoverable_minor"])]
             for r in by_provider],
            "lrrrrr",
        ),
        "## By month",
        md_table(["Provider", "Direction"] + [month(m) for m in months], month_rows, "ll" + "r" * len(months)),
        "## Dispute queue",
        "One row per provider invoice. Overcharges after the deadline can no longer be disputed under the contract.",
        md_table(
            ["Provider", "Invoice", "Invoice date", "Deadline", "Days left", "Status", "Overcharges", "Overcharge",
             "Recoverable", "Undercharge"],
            [[names.get(q["provider"], q["provider"]), q["invoice_id"], q["invoice_date"], q["earliest_deadline"],
              q["days_left"], q["status"], f"{q['overcharge_findings']:,}", eur(q["overcharge_minor"]),
              eur(q["recoverable_minor"]), eur(q["undercharge_minor"])] for q in queue],
            "llllrlrrrr",
        ),
    ])
    csv_out = csv_text(
        ["provider", "month", "finding_type", "direction", "findings", "difference_minor"],
        [[r["provider"], r["month"], r["finding_type"], r["direction"], r["findings"], r["difference_minor"]]
         for r in detail],
    )
    return {"findings_summary.md": md, "findings_summary.csv": csv_out}


# 3. Dispute packs ---------------------------------------------------------------------------------------------


def dispute_queue(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Invoices with at least one overcharge: the ones that get a dispute pack."""
    return rows(con, "select * from main.fct_dispute_queue where overcharge_findings > 0 order by provider, "
                     "statement_month, dispute_queue_id")


def pack_findings(con: duckdb.DuckDBPyConnection, dispute_queue_id: str) -> list[dict]:
    return rows(
        con,
        f"select {', '.join(PACK_COLUMNS)} from main.fct_findings where {DISPUTED} and {QUEUE_KEY} = ?"
        " order by finding_type, month, event_id nulls first, finding_id",
        [dispute_queue_id],
    )


def breached_clauses(con: duckdb.DuckDBPyConnection, dispute_queue_id: str) -> list[dict]:
    return rows(
        con,
        f"""
        with f as (select * from main.fct_findings where {DISPUTED} and {QUEUE_KEY} = ?)
        select t.contract_term_id, t.title, t.clause_text, t.contract_name, t.dispute_window_days,
            count(*) as findings, sum(f.difference_minor) as difference_minor,
            list_sort(list(distinct f.finding_type)) as finding_types
        from f
        inner join main.dim_contract_terms as t
            on t.contract_term_id = f.contract_id || ' v' || f.contract_version || ' §' || f.clause
        group by all
        order by t.contract_term_id
        """,
        [dispute_queue_id],
    )


def _letter(q: dict, findings: list[dict], clauses: list[dict], as_of: str) -> str:
    name = clauses[0]["contract_name"]
    contract_ids = sorted({f["contract_id"] for f in findings})
    window = sorted({c["dispute_window_days"] for c in clauses})
    by_type: dict[str, list] = defaultdict(lambda: [0, 0])
    for f in findings:
        by_type[f["finding_type"]][0] += 1
        by_type[f["finding_type"]][1] += f["difference_minor"]
    total = sum(f["difference_minor"] for f in findings)
    deadline = q["earliest_deadline"]
    if q["days_left"] >= 0:
        request = (
            f"We ask you to issue a credit note of **EUR {eur(total)}** against invoice {q['invoice_id']}, or to "
            f"explain any line you consider correct, before **{deadline}**, the end of the "
            f"{'/'.join(str(w) for w in window)}-day dispute window from the invoice date."
        )
    else:
        request = (
            f"The {'/'.join(str(w) for w in window)}-day dispute window for this invoice closed on **{deadline}** "
            f"({-q['days_left']} days before {as_of}). We record the overcharge of **EUR {eur(total)}** and ask "
            "you to review it; a credit is no longer due under the contract."
        )
    lines = [
        f"# Request for credit: invoice {q['invoice_id']}",
        "",
        f"- **To:** {name} (contract {', '.join(contract_ids)})",
        "- **From:** Fernway, payments finance",
        f"- **Invoice:** {q['invoice_id']}, dated {q['invoice_date']}, statement month {month(q['statement_month'])}",
        f"- **Overcharged charges:** {len(findings):,}",
        f"- **Total overcharge:** EUR {eur(total)}",
        f"- **Dispute deadline:** {deadline} ({'open' if q['days_left'] >= 0 else 'passed'} as of {as_of})",
        "",
        f"We checked every line of invoice {q['invoice_id']} against our contract. {len(findings):,} charges are "
        f"above what the contract allows, by EUR {eur(total)} in total. Each one is listed in `findings.csv` with "
        "the expected calculation, the amount billed and the source rows it was checked against.",
        "",
        "## Clauses breached",
        "",
        md_table(
            ["Clause", "Term", "Charges", "Overcharge (EUR)"],
            [[c["contract_term_id"], f"**{c['title']}.** {c['clause_text']}", f"{c['findings']:,}",
              eur(c["difference_minor"])] for c in clauses],
            "llrr",
        ),
        "",
        "## By type of error",
        "",
        md_table(
            ["Error", "Charges", "Overcharge (EUR)"],
            [[label(t), f"{n:,}", eur(m)] for t, (n, m) in sorted(by_type.items(), key=lambda i: label(i[0]))],
            "lrr",
        ),
        "",
        "## Request",
        "",
        request,
    ]
    return "\n".join(lines)


def dispute_packs(con: duckdb.DuckDBPyConnection, as_of: str) -> dict[str, str]:
    out = {}
    for q in dispute_queue(con):
        findings = pack_findings(con, q["dispute_queue_id"])
        clauses = breached_clauses(con, q["dispute_queue_id"])
        folder = f"dispute_packs/{q['provider']}/{q['dispute_queue_id']}"
        out[f"{folder}/findings.csv"] = csv_text(PACK_COLUMNS, [[f[c] for c in PACK_COLUMNS] for f in findings])
        out[f"{folder}/letter.md"] = _letter(q, findings, clauses, as_of)
    return out


def example_pack(con: duckdb.DuckDBPyConnection) -> dict:
    """The open invoice covering the most error types (ties: more money recoverable, then queue id)."""
    return rows(
        con,
        "select * from main.fct_dispute_queue where overcharge_findings > 0 and status = 'open'"
        " order by len(finding_types) desc, recoverable_minor desc, dispute_queue_id limit 1",
    )[0]


# 4. Provider comparison ---------------------------------------------------------------------------------------


def comparison_totals(con: duckdb.DuckDBPyConnection) -> list[dict]:
    return rows(
        con,
        """
        select card_segment, actual_provider, alternative_provider, sum(payments) as payments,
            sum(volume_minor) as volume_minor, sum(actual_billed_minor) as actual_billed_minor,
            sum(actual_expected_minor) as actual_expected_minor,
            sum(alternative_expected_minor) as alternative_expected_minor, sum(saving_minor) as saving_minor,
            min(month) as first_month, max(month) as last_month
        from main.fct_provider_comparison
        group by all order by card_segment, actual_provider, alternative_provider
        """,
    )


def best_switch_sentence(con: duckdb.DuckDBPyConnection) -> str:
    names = contract_names(con)
    totals = comparison_totals(con)
    best = max(totals, key=lambda r: (r["saving_minor"], r["card_segment"], r["actual_provider"]))
    span = f"{month(best['first_month'])} to {month(best['last_month'])}"
    if best["saving_minor"] <= 0:
        return f"No switch of a card segment would have lowered the payment fees from {span}."
    return (
        f"The switch that would have saved the most: moving {names.get(best['actual_provider'])}'s "
        f"`{best['card_segment']}` volume (EUR {eur(best['volume_minor'])}, {best['payments']:,} payments) to "
        f"{names.get(best['alternative_provider'])}'s contract, EUR {eur(best['saving_minor'])} from {span} "
        f"({rate_pct(best['actual_expected_minor'], best['volume_minor'])} instead of "
        f"{rate_pct(best['alternative_expected_minor'], best['volume_minor'])} of volume)."
    )


def comparison_table(con: duckdb.DuckDBPyConnection) -> str:
    names = contract_names(con)
    return md_table(
        ["Segment", "Processed by", "Volume", "Billed", "Under own contract", "Rate", "Under the other contract",
         "Rate", "Saving if switched"],
        [[r["card_segment"], names.get(r["actual_provider"]), eur(r["volume_minor"]), eur(r["actual_billed_minor"]),
          eur(r["actual_expected_minor"]), rate_pct(r["actual_expected_minor"], r["volume_minor"]),
          f"{eur(r['alternative_expected_minor'])} ({names.get(r['alternative_provider'])})",
          rate_pct(r["alternative_expected_minor"], r["volume_minor"]), eur(r["saving_minor"])]
         for r in comparison_totals(con)],
        "lllrrrrrr",
    )


def provider_comparison(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    names = contract_names(con)
    data = rows(con, "select * from main.fct_provider_comparison order by card_segment, actual_provider, month")
    md = "\n\n".join([
        "# Provider comparison",
        "What each card segment's succeeded payments cost under the contract of the provider that processed them, "
        "and what they would have cost under the other card provider's contract. Payment-level fees only "
        "(interchange, scheme fee, markup and fixed fee, or the blended rate), each provider's own month volume "
        "for its tiers; refund and chargeback fees, minimums and volume discounts are left out (assumption A23). "
        "Amounts in EUR; a positive saving means the other contract would have been cheaper. "
        "Source: `fct_provider_comparison`.",
        best_switch_sentence(con),
        "## Whole period",
        comparison_table(con),
        "## By month",
        md_table(
            ["Segment", "Processed by", "Month", "Payments", "Volume", "Own contract", "Other contract", "Saving"],
            [[r["card_segment"], names.get(r["actual_provider"]), month(r["month"]), f"{r['payments']:,}",
              eur(r["volume_minor"]), eur(r["actual_expected_minor"]), eur(r["alternative_expected_minor"]),
              eur(r["saving_minor"])] for r in data],
            "lllrrrrr",
        ),
    ])
    csv_out = csv_text(
        ["card_segment", "month", "actual_provider", "alternative_provider", "payments", "volume_minor",
         "actual_billed_minor", "actual_expected_minor", "alternative_expected_minor", "saving_minor",
         "actual_rate_bps", "alternative_rate_bps"],
        [[r["card_segment"], month(r["month"]), r["actual_provider"], r["alternative_provider"], r["payments"],
          r["volume_minor"], r["actual_billed_minor"], r["actual_expected_minor"], r["alternative_expected_minor"],
          r["saving_minor"], r["actual_rate_bps"], r["alternative_rate_bps"]] for r in data],
    )
    return {"provider_comparison.md": md, "provider_comparison.csv": csv_out}
