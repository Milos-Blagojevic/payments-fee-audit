"""`python -m feeaudit.reference [--db warehouse/fees.duckdb]`"""

import argparse

import duckdb

from feeaudit.reference import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute reference.expected_charges from contracts and the raw ledger.")
    parser.add_argument("--db", default="warehouse/fees.duckdb", help="DuckDB file with the raw schema")
    args = parser.parse_args()
    with duckdb.connect(args.db) as con:
        rows = run(con)
    print(f"reference.expected_charges: {len(rows)} rows written to {args.db}")


if __name__ == "__main__":
    main()
