"""Write the finance outputs to reports/, the committed sample to reports/examples/, the headline chart and the
README generated blocks. Reads the marts and schema `evaluation` of the built warehouse."""

import argparse
import shutil
import sys
from pathlib import Path

import duckdb

from feeaudit.reports import client, finance, readme, trace
from feeaudit.reports.common import as_of_date, write

EXAMPLES = ["findings_summary.md", "provider_costs.md", "provider_comparison.md", "follow_one_finding.md",
            "client_report.md"]


def outputs(con: duckdb.DuckDBPyConnection, as_of: str) -> dict[str, str]:
    """Every report file, by path relative to the output directory."""
    files: dict[str, str] = {}
    files.update(finance.provider_costs(con))
    files.update(finance.findings_summary(con, as_of))
    files.update(finance.dispute_packs(con, as_of))
    files.update(finance.provider_comparison(con))
    files.update(client.client_report(con))
    files["follow_one_finding.md"] = trace.render(con)
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="warehouse/fees.duckdb")
    parser.add_argument("--out", default="reports")
    parser.add_argument("--readme", default="README.md")
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"{args.db} not found; run `make all`", file=sys.stderr)
        return 2
    out = Path(args.out)
    as_of = as_of_date()
    with duckdb.connect(args.db, read_only=True) as con:
        con.execute("SET enable_progress_bar = false")
        files = outputs(con, as_of)
        pack = finance.example_pack(con)
        blocks = readme.blocks(con, as_of)
        chart = readme.chart_svg(con)

    for stale in ("dispute_packs", "examples"):
        shutil.rmtree(out / stale, ignore_errors=True)
    for name, text in files.items():
        write(out / name, text)

    pack_dir = f"dispute_packs/{pack['provider']}/{pack['dispute_queue_id']}"
    for name in EXAMPLES + [f"{pack_dir}/letter.md", f"{pack_dir}/findings.csv"]:
        write(out / "examples" / name, files[name])

    write(readme.CHART_PATH, chart)
    readme_path = Path(args.readme)
    readme_path.write_text(readme.render(readme_path.read_text(encoding="utf-8"), blocks), encoding="utf-8")

    packs = sum(1 for name in files if name.endswith("letter.md"))
    print(f"wrote {len(files)} files to {out}/ ({packs} dispute packs), examples to {out}/examples/, "
          f"{readme.CHART_PATH} and {readme_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
