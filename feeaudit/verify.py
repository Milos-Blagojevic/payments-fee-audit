"""Differential check: Python reference expected charges vs the dbt engine's.

`python -m feeaudit.verify [--db warehouse/fees.duckdb] [--dbt-table main.int_expected_charges]`
exits non-zero on any missing row, duplicate key or amount difference, and records the outcome in
`verification.check_results` (replaced each run) for the metrics MCP server's `differential` check.
"""

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import NamedTuple

import duckdb

REFERENCE_TABLE = "reference.expected_charges"
DBT_TABLE = "main.int_expected_charges"
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*){0,2}$")


class Difference(NamedTuple):
    kind: str  # missing_in_dbt, missing_in_reference, amount, duplicate_in_reference, duplicate_in_dbt
    provider: str
    component: str
    event_type: str
    event_key: str  # event_id, or the month for provider_month rows
    reference_minor: int | None
    dbt_minor: int | None


def _keyed(table: str) -> str:
    if not _IDENTIFIER.match(table):
        raise ValueError(f"not a table name: {table!r}")
    return (
        "select provider, component, event_type,"
        " coalesce(event_id, cast(month as varchar)) as event_key, expected_minor"
        f" from {table}"
    )


def compare(
    con: duckdb.DuckDBPyConnection, reference_table: str = REFERENCE_TABLE, dbt_table: str = DBT_TABLE
) -> list[Difference]:
    """All differences between the two tables on (provider, component, event_type, coalesce(event_id, month))."""
    differences = []
    for side, table in (("reference", reference_table), ("dbt", dbt_table)):
        for provider, component, event_type, event_key, count in con.execute(
            f"select provider, component, event_type, event_key, count(*) from ({_keyed(table)})"
            " group by all having count(*) > 1"
        ).fetchall():
            differences.append(Difference(f"duplicate_in_{side}", provider, component, event_type, event_key, None, None))
    rows = con.execute(
        f"""
        with r as ({_keyed(reference_table)}), d as ({_keyed(dbt_table)})
        select
            provider, component, event_type, event_key,
            r.event_key is not null as in_reference,
            d.event_key is not null as in_dbt,
            r.expected_minor, d.expected_minor
        from r full outer join d using (provider, component, event_type, event_key)
        where r.event_key is null or d.event_key is null
            or r.expected_minor is distinct from d.expected_minor
        """
    ).fetchall()
    for provider, component, event_type, event_key, in_reference, in_dbt, ref_minor, dbt_minor in rows:
        kind = "amount" if in_reference and in_dbt else "missing_in_dbt" if in_reference else "missing_in_reference"
        differences.append(Difference(kind, provider, component, event_type, event_key, ref_minor, dbt_minor))
    differences.sort(key=lambda d: (d.provider, d.event_type, d.event_key, d.component, d.kind))
    return differences


def record(con: duckdb.DuckDBPyConnection, passed: bool, detail: str) -> None:
    """Replace the outcome in `verification.check_results`; the metrics MCP server reads it (A52)."""
    con.execute("create schema if not exists verification")
    con.execute(
        "create or replace table verification.check_results"
        " (check_name varchar, passed boolean, detail varchar, checked_at timestamp)"
    )
    con.execute(
        "insert into verification.check_results values ('differential', ?, ?, ?)",
        [passed, detail, datetime.now(timezone.utc).replace(tzinfo=None)],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare reference.expected_charges with the dbt expected charges.")
    parser.add_argument("--db", default="warehouse/fees.duckdb")
    parser.add_argument("--dbt-table", default=DBT_TABLE)
    args = parser.parse_args(argv)
    with duckdb.connect(args.db) as con:
        differences = compare(con, REFERENCE_TABLE, args.dbt_table)
        counts = Counter(d.kind for d in differences)
        summary = ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
        detail = (f"{REFERENCE_TABLE} equals {args.dbt_table}" if not differences
                  else f"{len(differences)} differences between {REFERENCE_TABLE} and {args.dbt_table} ({summary})")
        record(con, not differences, detail)
    if not differences:
        print(f"OK: {detail}")
        return 0
    print(f"FAIL: {len(differences)} differences ({summary})")
    print("First ten:")
    for d in differences[:10]:
        print(
            f"  {d.kind:<21} {d.provider} {d.event_type} {d.event_key} {d.component}:"
            f" reference={d.reference_minor} dbt={d.dbt_minor}"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
