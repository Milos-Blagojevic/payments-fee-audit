"""Evaluate the findings against the planted truth; writes schema `evaluation`, exits 1 below the thresholds."""

import argparse
import sys
from pathlib import Path

import duckdb

from feeaudit.evaluation.evaluate import THRESHOLDS, Result, evaluate


def eur(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100:,}.{abs(minor) % 100:02d}"


def summary(result: Result) -> str:
    lines = ["type  finding_type                    planted  found  findings  TP   precision  recall  planted EUR    found EUR"]
    for r in result.detection:
        lines.append(
            f"{r['truth_id']:<5} {r['finding_type']:<31} {r['planted']:>7} {r['found']:>6} {r['findings']:>9} "
            f"{r['true_positives']:>4} {r['precision']:>10.3f} {r['recall']:>7.3f} "
            f"{eur(r['planted_minor']):>12} {eur(r['found_minor']):>12}"
        )
    if not result.client_evaluated:
        lines.append("(client findings table absent: L types not evaluated)")
    lines += [
        "",
        f"money recall           {result.money_recall:.4f}",
        f"noise false positives  {result.noise_fp}",
        f"rounding off N08 rows  {result.rounding_off_n08}",
        f"unexplained findings   {result.unexplained}",
        f"thresholds             {THRESHOLDS}",
        "",
    ]
    lines += [f"FAIL {f}" for f in result.failures] or ["PASS"]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="warehouse/fees.duckdb")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"{args.db} not found; run `make all`", file=sys.stderr)
        return 2
    with duckdb.connect(args.db) as con:
        con.execute("SET enable_progress_bar = false")
        try:
            result = evaluate(con)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
    print(summary(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
