"""Generated blocks of README.md and docs/walkthrough.md, and the headline chart.

Every block sits between `<!-- generated:<name> -->` and `<!-- /generated -->` in one of the two files; the prose
around the blocks is hand-written and never touched. Rendering twice gives the same files.
"""

import ast
import json
import re
from html import escape
from pathlib import Path

import duckdb

from feeaudit.extraction.budget import load_ledger, spent, usd
from feeaudit.extraction.extract import LEDGER, OUT_DIR, RECORDED
from feeaudit.extraction.score import accuracy
from feeaudit.reports import client, finance
from feeaudit.reports.common import dbt_var, eur, label, md_table, rows
from feeaudit.verify import DBT_TABLE, REFERENCE_TABLE, compare

BLOCK = re.compile(r"(<!-- generated:([\w-]+) -->\n)(.*?)(<!-- /generated -->)", re.DOTALL)

README = Path("README.md")
WALKTHROUGH = Path("docs/walkthrough.md")
DOCS_ROOT = "../"  # relative path from docs/ back to the repository root, for links in the walkthrough's blocks
CHART_PATH = Path("docs/img/money-found-by-type.svg")
MANIFEST = Path("dbt/target/manifest.json")
SPEND_LEDGER = OUT_DIR / RECORDED / LEDGER

# Section 3: the clause quoted from the real files.
CLAUSE_YAML = Path("contracts/providers/northgate-v2.yml")
CLAUSE = "4.2"
CLAUSE_SQL = Path("dbt/models/intermediate/int_expected_charges.sql")
CLAUSE_SQL_START = "-- Clause 4.2 "
CLAUSE_SQL_CTE = "markup_rows as ("
CLAUSE_PY = Path("feeaudit/reference/terms.py")
CLAUSE_PY_FUNCTIONS = ("tier_bps", "markup_retroactive", "bps_of")

# How each noise type of data contract section 6 is handled.
NOISE_HANDLING = {
    "N01": "Exact repeated rows (same line id) in a re-exported file are kept once in staging.",
    "N02": "Amounts are parsed per source: minor units, major units, or comma decimals with `;` delimiters.",
    "N03": "Local times without an offset are converted from Europe/Berlin to UTC in staging.",
    "N04": "Late lines in the next month's file are matched by event, and disputed on the invoice that billed them.",
    "N05": "Currency codes and card labels are trimmed and mapped to one vocabulary.",
    "N06": "Lines without a reference are matched by amount, currency, client and ±48 h, one to one.",
    "N07": "Lines after the ledger watermark are `unmatched_pending`, never findings.",
    "N08": "One-cent ties rounded the other way are `rounding` findings, never overcharges.",
}


# Headline chart ------------------------------------------------------------------------------------------------


def chart_svg(con: duckdb.DuckDBPyConnection) -> str:
    """Horizontal bars: money found by finding type (absolute EUR; undercharges marked)."""
    data = finance.findings_by_type(con)
    bars = [(r["truth_id"], label(r["finding_type"]), r["over_minor"] + r["under_minor"]) for r in data]
    bars.sort(key=lambda b: (-abs(b[2]), b[0]))
    top = max((abs(b[2]) for b in bars), default=0) or 1
    left, bar_area, row_h, head = 330, 330, 26, 44
    width = left + bar_area + 110
    height = head + row_h * len(bars) + 16
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"'
        ' font-family="Helvetica, Arial, sans-serif" font-size="13">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<text x="16" y="26" font-size="15" font-weight="bold" fill="#1f2933">'
        "Money found by type of billing error (EUR, synthetic data)</text>",
    ]
    for i, (truth_id, name, minor) in enumerate(bars):
        y = head + i * row_h
        w = max(1, round(abs(minor) * bar_area / top))
        colour = "#2f6f9f" if minor >= 0 else "#c2772c"
        value = eur(abs(minor)) + ("" if minor >= 0 else " under")
        out += [
            f'<text x="{left - 8}" y="{y + 15}" text-anchor="end" fill="#1f2933">{escape(truth_id)} '
            f"{escape(name)}</text>",
            f'<rect x="{left}" y="{y + 3}" width="{w}" height="{row_h - 8}" fill="{colour}"/>',
            f'<text x="{left + w + 6}" y="{y + 15}" fill="#3e4c59">{escape(value)}</text>',
        ]
    out.append("</svg>")
    return "\n".join(out) + "\n"


# Blocks --------------------------------------------------------------------------------------------------------


def block_headline(con, as_of: str) -> str:
    return "\n\n".join([
        finance.findings_headline(con, as_of),
        f"![Money found by type of billing error]({CHART_PATH.as_posix()})",
    ])


def block_world(con) -> str:
    contracts = rows(
        con,
        """
        select counterparty, contract_name, contract_id, contract_version, effective_from, effective_to,
            dispute_window_days, string_agg(clause || ' ' || title, '; ' order by clause) as clauses
        from main.dim_contract_terms where party = 'provider'
        group by all order by counterparty, contract_version
        """,
    )
    clients = con.execute("select count(*) from main.stg_fernway__clients").fetchone()[0]
    ledger = rows(
        con,
        """
        select 'payments' as events, count(*) as n, min(created_at_utc) as first, max(created_at_utc) as last
            from main.stg_ledger__payments
        union all select 'refunds', count(*), min(created_at_utc), max(created_at_utc) from main.stg_ledger__refunds
        union all select 'chargebacks', count(*), min(created_at_utc), max(created_at_utc)
            from main.stg_ledger__chargebacks
        union all select 'payouts', count(*), min(created_at_utc), max(created_at_utc) from main.stg_ledger__payouts
        """,
    )
    lines = con.execute("select count(*) from main.int_reconciliation").fetchone()[0]
    planted = rows(con, "select truth_id, finding_type, planted, planted_minor from evaluation.detection_by_type "
                        "order by truth_id")
    first = min(r["first"] for r in ledger)
    last = max(r["last"] for r in ledger)
    return "\n\n".join([
        f"Ledger: {', '.join(f'{r['n']:,} {r['events']}' for r in ledger)} for {clients} clients, "
        f"{first:%Y-%m-%d} to {last:%Y-%m-%d}; {lines:,} provider lines to check.",
        md_table(
            ["Provider", "Contract", "Version", "In force", "Dispute window", "Clauses"],
            [[r["contract_name"], r["contract_id"], r["contract_version"],
              f"{r['effective_from']} to {r['effective_to'] or 'open'}", f"{r['dispute_window_days']} days",
              r["clauses"]] for r in contracts],
        ),
        "Planted billing errors (counted from the generator's truth by the evaluation step):",
        md_table(
            ["Type", "Error", "Planted", "Money (EUR)"],
            [[r["truth_id"], label(r["finding_type"]), f"{r['planted']:,}", eur(r["planted_minor"])]
             for r in planted],
            "llrr",
        ),
    ])


def _yaml_clause() -> tuple[str, int, int]:
    lines = CLAUSE_YAML.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == f'- clause: "{CLAUSE}"')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("- clause:")), len(lines))
    return "\n".join(lines[start:end]), start + 1, end


def _sql_clause() -> tuple[str, int, int]:
    lines = CLAUSE_SQL.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(CLAUSE_SQL_START))
    cte = next(i for i in range(start, len(lines)) if lines[i].strip() == CLAUSE_SQL_CTE)
    end = next(i for i in range(cte, len(lines)) if lines[i] == "),")
    return "\n".join(lines[start:end + 1]), start + 1, end + 1


def _python_functions() -> list[tuple[str, int, int]]:
    source = CLAUSE_PY.read_text()
    tree = ast.parse(source)
    found = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    return [(ast.get_source_segment(source, found[name]), found[name].lineno, found[name].end_lineno)
            for name in CLAUSE_PY_FUNCTIONS]


def block_contract_to_rule(con, root: str) -> str:
    """One clause as YAML, SQL and Python; `root` prefixes the file links (the block lives under docs/)."""
    term = rows(con, "select * from main.dim_contract_terms where source_file = ? and clause = ?",
                [CLAUSE_YAML.as_posix(), CLAUSE])[0]
    yaml_text, y0, y1 = _yaml_clause()
    sql_text, s0, s1 = _sql_clause()
    functions = _python_functions()
    py_text = "\n\n\n".join(f[0] for f in functions)
    return "\n\n".join([
        f"**The clause** ({term['contract_term_id']}, *{term['title']}*), as `dim_contract_terms` states it: "
        f"{term['clause_text']}",
        f"In the contract file, [`{CLAUSE_YAML}`]({root}{CLAUSE_YAML}) lines {y0}–{y1}:",
        f"```yaml\n{yaml_text}\n```",
        f"**The SQL** that turns it into an expected charge per payment, "
        f"[`{CLAUSE_SQL}`]({root}{CLAUSE_SQL}) lines {s0}–{s1}:",
        f"```sql\n{sql_text}\n```",
        f"**The Python reference**, written separately from the SQL, "
        f"[`{CLAUSE_PY}`]({root}{CLAUSE_PY}) ({', '.join(f'lines {a}–{b}' for _, a, b in functions)}):",
        f"```python\n{py_text}\n```",
    ])


def block_lineage() -> str:
    manifest = json.loads(MANIFEST.read_text())
    nodes = {k: v for k, v in manifest["nodes"].items() if v["resource_type"] in ("model", "seed")}
    layers = {"staging": [], "intermediate": [], "marts": [], "seeds": []}
    for key, node in nodes.items():
        layer = "seeds" if node["resource_type"] == "seed" else node["fqn"][1]
        layers[layer].append(node["name"])
    edges = sorted({(nodes[dep]["name"], node["name"]) for node in nodes.values()
                    for dep in node.get("depends_on", {}).get("nodes", []) if dep in nodes})
    sources = sorted({manifest["sources"][dep]["source_name"] for node in nodes.values()
                      for dep in node.get("depends_on", {}).get("nodes", []) if dep.startswith("source.")})
    out = ["```mermaid", "flowchart LR"]
    out.append(f"  raw[(\"sources: {', '.join(sources)}\")]")
    for layer in ("seeds", "staging", "intermediate", "marts"):
        if layers[layer]:
            out.append(f"  subgraph {layer}")
            out += [f"    {name}" for name in sorted(layers[layer])]
            out.append("  end")
    out.append("  raw --> staging")
    out += [f"  {a} --> {b}" for a, b in edges]
    out.append("```")
    return "\n".join(out)


def block_reconciliation(con) -> str:
    data = rows(
        con,
        """
        select status, coalesce(match_method, '') as match_method, coalesce(reason, '') as reason,
            count(*) filter (where provider = 'northgate') as northgate,
            count(*) filter (where provider = 'brightpay') as brightpay,
            count(*) filter (where provider = 'kestrel') as kestrel,
            count(*) as lines
        from main.int_reconciliation group by all order by status, match_method, reason
        """,
    )
    return md_table(
        ["Status", "Matched by", "Reason", "Northgate", "Brightpay", "Kestrel", "All lines"],
        [[f"`{r['status']}`", r["match_method"], r["reason"], f"{r['northgate']:,}", f"{r['brightpay']:,}",
          f"{r['kestrel']:,}", f"{r['lines']:,}"] for r in data],
        "lllrrrr",
    )


def block_noise(con) -> str:
    fp = dict(con.execute("select noise_id, count(*) from evaluation.noise_false_positives "
                          "where category = 'noise' group by 1").fetchall())
    return md_table(
        ["Noise", "Handling", "False findings on noise rows"],
        [[n, text, fp.get(n, 0)] for n, text in NOISE_HANDLING.items()],
        "llr",
    )


def block_evaluation(con) -> str:
    data = rows(con, "select * from evaluation.detection_by_type order by truth_id")
    noise_fp = con.execute("select count(*) from evaluation.noise_false_positives").fetchone()[0]
    unexplained = con.execute("select count(*) from evaluation.unexplained_findings").fetchone()[0]
    reference_rows = con.execute(f"select count(*) from {REFERENCE_TABLE}").fetchone()[0]
    dbt_rows = con.execute(f"select count(*) from {DBT_TABLE}").fetchone()[0]
    differences = compare(con)
    return "\n\n".join([
        md_table(
            ["Type", "Error", "Planted", "Found", "Precision", "Recall", "Planted EUR", "Found EUR"],
            [[r["truth_id"], label(r["finding_type"]), f"{r['planted']:,}", f"{r['found']:,}",
              f"{r['precision']:.3f}", f"{r['recall']:.3f}", eur(r["planted_minor"]), eur(r["found_minor"])]
             for r in data],
            "llrrrrrr",
        ),
        "\n".join([
            f"- False findings on noise rows: **{noise_fp}**.",
            f"- Findings that match no planted error and are not rounding noise: **{unexplained}**.",
            f"- Differential check: the Python reference engine computed {reference_rows:,} expected charges, the "
            f"dbt models {dbt_rows:,}; **{len(differences)}** differ in key or amount.",
        ]),
    ])


def _planted_anomaly(r: dict, names: dict) -> str:
    cards = "every payment" if r["card_segment"] == "all" else f"every `{r['card_segment']}` payment"
    text = (
        f"{r['anomaly_id']}: from {r['start_date']}, {names.get(r['provider'], r['provider'])} bills a line type no "
        f"contract names, `{r['line_type']}` ({r['rate_bps']} bps of {cards}; {r['planted_lines']:,} lines and "
        f"EUR {eur(r['planted_minor'])} by the end of the period)."
    )
    if not r["detected"]:
        return text + " It was not detected."
    when = "the day it started" if r["days_to_detect"] == 0 else f"{r['days_to_detect']} days after it started"
    kind = {"new_component": "new fee component", "rate_shift": "rate shift"}.get(r["anomaly_type"], r["anomaly_type"])
    return (text + f" It was caught on {r['first_detected_day']}, {when}, as a {kind}. The anomaly finding "
            f"reads:\n\n  > {r['explanation']}")


def block_anomalies(con) -> str:
    window, threshold = dbt_var("anomaly_window_days"), dbt_var("anomaly_z_threshold")
    names = finance.contract_names(con)
    report = rows(con, "select * from evaluation.anomaly_report order by category desc, anomaly_id, "
                       "detected_anomaly_id")
    planted = [r for r in report if r["category"] == "planted"]
    other = [r for r in report if r["category"] == "not_planted"]
    by_contract = sum(r["explained_by"] == "contract" for r in other)
    by_rules = sum(r["explained_by"] == "rule_findings" for r in other)
    findings = sum(bool(r["is_finding"]) for r in other)
    return "\n\n".join([
        f"Each day, the effective rate of every provider × fee component × card segment (billed ÷ the day's "
        f"processed volume, in basis points) is compared with its median over the previous {window} days: robust "
        f"z = 0.6745 × (rate − median) ÷ MAD, the median absolute deviation, flagged when |z| > {threshold}; when "
        f"the MAD is 0, the mean absolute deviation takes its place (A10, A42). A fee component that no version of "
        f"the provider's contract names is flagged on the first day it is billed, once the provider has {window} "
        f"days of history (A43).",
        finance.anomaly_counts_table(con),
        f"The generator planted {len(planted)} pattern{'s' if len(planted) != 1 else ''} that no rule describes "
        "(`config/generator.yml`, `truth.anomalies`):",
        "\n".join(f"- {_planted_anomaly(r, names)}" for r in planted) or "- none",
        f"{len(other):,} flagged days match no planted pattern: {by_contract:,} are explained by the contract (every "
        f"charge of the day equals its expected amount, as on a new markup tier or contract version), {by_rules:,} "
        f"by rule findings on the same charges, and {findings:,} became anomaly findings.",
        "Anomaly findings are reported, not disputed: no clause backs them, so they stay out of the dispute queue and "
        "the dispute packs, and the evaluation reports them without a target.",
    ])


# The README's reading list, in the order a first reader should take it; the dispute pack is appended from the build.
EXAMPLES = [
    ("findings_summary.md", "Findings summary", "overcharge and undercharge by provider, type and month; what can "
                                                "still be disputed against what is past its deadline; anomalies, "
                                                "reported but not disputed"),
    ("follow_one_finding.md", "Follow one finding", "one finding traced from the provider's raw file row through "
                                                    "staging, the reconciliation match and the expected charge with "
                                                    "its formula, to the finding"),
    ("client_report.md", "Client report", "the same checks on Fernway's own invoices: revenue leakage by client, "
                                          "type and month, and margin per client"),
    ("provider_costs.md", "Monthly provider cost report", "volume, fees by component, effective and markup rates "
                                                          "by provider and card segment, change against the "
                                                          "previous month"),
    ("provider_comparison.md", "Provider comparison", "cost per card segment under each card contract"),
]


def block_examples(pack: dict) -> str:
    folder = f"reports/examples/dispute_packs/{pack['provider']}/{pack['dispute_queue_id']}"
    items = [f"- [{title}](reports/examples/{name}): {text}." for name, title, text in EXAMPLES]
    items.insert(2, (
        f"- Dispute pack for invoice {pack['invoice_id']}: [letter]({folder}/letter.md) and "
        f"[line-level findings]({folder}/findings.csv), clause-cited ({pack['overcharge_findings']:,} overcharges, "
        f"EUR {eur(pack['overcharge_minor'])}, deadline {pack['earliest_deadline']})."
    ))
    return "\n".join(items)


def block_provider_comparison(con) -> str:
    return finance.best_switch_sentence(con) + "\n\n" + finance.comparison_table(con)


def block_revenue_side(con) -> str:
    planted = rows(con, "select truth_id, finding_type, planted, found, planted_minor, found_minor"
                        " from evaluation.detection_by_type where truth_id like 'L%' order by truth_id")
    return "\n\n".join([
        client.headline(con),
        "Planted against found, from the evaluation (money as the planted difference, negative = billed too little):",
        md_table(
            ["Type", "Error", "Planted", "Found", "Planted EUR", "Found EUR"],
            [[r["truth_id"], label(r["finding_type"]), f"{r['planted']:,}", f"{r['found']:,}",
              eur(r["planted_minor"]), eur(r["found_minor"])] for r in planted],
            "llrrrr",
        ),
        "All client findings by type:",
        client.leakage_type_table(con),
        client.allocation_text(con),
    ])


def block_extraction(con) -> str:
    """Accuracy of the recorded LLM extractions (evaluation.extraction_scores) and what they cost (spend ledger)."""
    ledger = load_ledger(SPEND_LEDGER)
    calls = ledger["calls"]
    if not calls:
        return "No extraction has been recorded yet: `contracts/extracted/` is empty, so there is nothing to score."
    versions = rows(
        con,
        """
        select contract, version, count(*) filter (where correct) as correct, count(*) as total
        from evaluation.extraction_scores group by all order by contract, version
        """,
    )
    wrong = rows(
        con,
        """
        select contract, version, field_path, expected, extracted from evaluation.extraction_scores
        where not correct order by contract, version, field_path
        """,
    )
    correct, total = sum(v["correct"] for v in versions), sum(v["total"] for v in versions)
    models = sorted({c["model"] for c in calls})
    parts = [
        f"{len(calls)} recorded call(s) to {', '.join(f'`{m}`' for m in models)} cost USD {usd(spent(ledger))} "
        f"in total. Field accuracy against the hand-written contract files: {accuracy(correct, total)} "
        f"({correct:,} of {total:,} fields).",
        md_table(
            ["Contract", "Version", "Fields correct", "Accuracy"],
            [[v["contract"], str(v["version"]), f"{v['correct']:,} / {v['total']:,}", accuracy(v["correct"], v["total"])]
             for v in versions],
            "lrrr",
        ),
    ]
    if wrong:
        parts.append("Fields the model got wrong (each would be caught at the approval step):")
        parts.append(md_table(
            ["Contract", "Version", "Field", "Contract file", "Extracted"],
            [[w["contract"], str(w["version"]), f"`{w['field_path']}`", f"`{w['expected']}`", f"`{w['extracted']}`"]
             for w in wrong],
            "lrlll",
        ))
    return "\n\n".join(parts)


def blocks(con: duckdb.DuckDBPyConnection, as_of: str) -> dict[str, str]:
    return {
        "headline": block_headline(con, as_of),
        "examples": block_examples(finance.example_pack(con)),
        "world": block_world(con),
        "contract-to-rule": block_contract_to_rule(con, DOCS_ROOT),
        "lineage": block_lineage(),
        "reconciliation": block_reconciliation(con),
        "noise": block_noise(con),
        "findings-summary": finance.findings_type_table(con),
        "evaluation": block_evaluation(con),
        "anomalies": block_anomalies(con),
        "provider-comparison": block_provider_comparison(con),
        "revenue-side": block_revenue_side(con),
        "extraction": block_extraction(con),
    }


def render(texts: dict[str, str], generated: dict[str, str]) -> dict[str, str]:
    """Replace the body of every generated block in each file (name -> text).

    Fails when a file holds a block with no generator, when a block appears in more than one file, or when a
    generated block appears in none."""
    seen: dict[str, str] = {}

    def replace_in(file: str):
        def replace(match: re.Match) -> str:
            name = match.group(2)
            if name not in generated:
                raise KeyError(f"{file}: block {name!r} has no generator")
            if name in seen:
                raise KeyError(f"block {name!r} is in both {seen[name]} and {file}")
            seen[name] = file
            return f"{match.group(1)}{generated[name].strip()}\n{match.group(4)}"
        return replace

    result = {file: BLOCK.sub(replace_in(file), text) for file, text in texts.items()}
    missing = sorted(set(generated) - set(seen))
    if missing:
        raise KeyError(f"{', '.join(texts)} lack the blocks {missing}")
    return result

