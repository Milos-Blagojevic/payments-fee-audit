"""Formatting and file helpers shared by the report writers. Money stays in integer minor units until printed."""

import csv
import io
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import duckdb
import yaml

DBT_PROJECT = Path("dbt/dbt_project.yml")

# Plain-language name of every finding type (data contract section 5).
TYPE_LABELS = {
    "stale_rate": "Markup at the rate before the amendment",
    "retroactive_tier_not_applied": "Volume tier not applied to the whole month",
    "pass_through_above_reference": "Interchange or scheme fee above cost",
    "refund_credit_missing": "Markup not credited on a refund",
    "minimum_not_due": "Monthly minimum charged when not due",
    "duplicate_charge": "Same payment charged twice",
    "wrong_card_segment": "Card priced in the wrong segment",
    "fee_on_failed_attempt": "Fee on a declined or failed attempt",
    "chargeback_fee_mismatch": "Chargeback fee above the contract",
    "volume_discount_not_applied": "Volume discount not applied",
    "fx_spread_above_cap": "FX spread above the cap",
    "fx_rate_wrong_hour": "FX rate from the wrong hour",
    "payout_fee_cap_not_applied": "Payout fee cap not applied",
    "unknown_charge": "Charge with no matching payment",
    "refund_fee_missing": "Refund fee not billed",
    "rounding": "Rounding (one cent, other rounding mode)",
    "fee_mismatch": "Difference no rule explains",
}


def label(finding_type: str) -> str:
    return TYPE_LABELS.get(finding_type, finding_type)


def eur(minor: int | None) -> str:
    """`1,234.56`, `-0.07`; minor units to a major-unit string without floats."""
    if minor is None:
        return ""
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100:,}.{abs(minor) % 100:02d}"


def rate_pct(numerator_minor: int | None, volume_minor: int | None) -> str:
    """numerator ÷ volume as a percentage with three decimals; blank without a volume."""
    if not volume_minor or numerator_minor is None:
        return ""
    value = Decimal(numerator_minor * 100) / Decimal(volume_minor)
    return f"{value.quantize(Decimal('0.001'), rounding=ROUND_HALF_EVEN)}%"


def pct_change(current: int, previous: int | None) -> str:
    if not previous:
        return ""
    value = (Decimal((current - previous) * 100) / Decimal(previous)).quantize(Decimal("0.1"), ROUND_HALF_EVEN)
    return "0.0%" if value == 0 else f"{value:+}%"


def month(value) -> str:
    return value.strftime("%Y-%m")


def md_table(headers: list[str], rows: list[list], align: str | None = None) -> str:
    """Markdown table; `align` is one character per column, `l` or `r` (default: left)."""
    align = align or "l" * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---:" if a == "r" else "---" for a in align) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if v is None else str(v).replace("|", "\\|") for v in row) + " |")
    return "\n".join(lines)


def csv_text(headers: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else ";".join(v) if isinstance(v, list) else v for v in row])
    return buffer.getvalue()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def as_of_date() -> str:
    return str(yaml.safe_load(DBT_PROJECT.read_text())["vars"]["as_of_date"])
