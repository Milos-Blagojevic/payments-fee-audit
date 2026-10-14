"""Loads data/raw into schema `raw` (as-is, all VARCHAR) and data/truth into schema `truth`.

Every directory data/raw/<source>/<entity>/ becomes table raw.<source>__<entity>, one row per data row of
each CSV file, plus `source_file` (path relative to the parent of the data directory) and `source_row`
(1-based data row number). Empty fields load as NULL; every other value is kept verbatim.
"""

import argparse
import csv
import sys
from pathlib import Path

import duckdb
import numpy as np

TRUTH_TYPES = {
    "discrepancies": {
        "discrepancy_id": "VARCHAR", "truth_id": "VARCHAR", "provider": "VARCHAR", "month": "VARCHAR",
        "event_id": "VARCHAR", "line_ids": "VARCHAR", "correct_minor": "BIGINT", "billed_minor": "BIGINT",
        "difference_minor": "BIGINT", "currency": "VARCHAR",
    },
    "client_leakage": {
        "truth_id": "VARCHAR", "client_id": "VARCHAR", "month": "VARCHAR", "component": "VARCHAR",
        "correct_minor": "BIGINT", "billed_minor": "BIGINT", "difference_minor": "BIGINT",
    },
    "noise_events": {
        "truth_id": "VARCHAR", "source_file": "VARCHAR", "source_row": "BIGINT", "line_id": "VARCHAR",
        "event_id": "VARCHAR",
    },
    "parameters": {"parameter": "VARCHAR", "value": "VARCHAR"},
}


def read_source(files, root):
    """Columns of all files of one source entity as numpy object arrays of str, plus source_file and source_row."""
    header, rows, source_file, source_row = None, [], [], []
    for path in files:
        with open(path, newline="") as f:
            first = f.readline()
            delimiter = ";" if first.count(";") > first.count(",") else ","
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            names = next(reader)
            if header is None:
                header = names
            elif names != header:
                raise ValueError(f"{path}: header {names} differs from {header}")
            file_rows = list(reader)
        bad = next((i for i, r in enumerate(file_rows, 1) if len(r) != len(header)), None)
        if bad:
            raise ValueError(f"{path}: row {bad} has {len(file_rows[bad - 1])} fields, expected {len(header)}")
        rows += file_rows
        source_file += [Path(path).resolve().relative_to(root).as_posix()] * len(file_rows)
        source_row += range(1, len(file_rows) + 1)
    columns = list(zip(*rows)) if rows else [()] * len(header)
    data = {name: np.array(c, dtype=object) for name, c in zip(header, columns)}
    data["source_file"] = np.array(source_file, dtype=object)
    data["source_row"] = np.array(source_row, dtype=np.int64)
    return data


def load(data_dir="data", db_path="warehouse/fees.duckdb"):
    """(Re)create schemas raw and truth; return {table: row count}."""
    data_dir = Path(data_dir).resolve()
    root = data_dir.parent
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with duckdb.connect(str(db_path)) as con:
        for schema in ("raw", "truth"):
            con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}")
        for entity_dir in sorted(p for p in (data_dir / "raw").glob("*/*") if p.is_dir()):
            files = sorted(entity_dir.glob("*.csv"))
            if not files:
                continue
            table = f"{entity_dir.parent.name}__{entity_dir.name}"
            frame = read_source(files, root)  # noqa: F841 (read by DuckDB's replacement scan)
            casts = ", ".join(
                f'NULLIF(CAST("{c}" AS VARCHAR), \'\') AS "{c}"' for c in frame if c not in ("source_file", "source_row")
            )
            con.execute(f'CREATE TABLE raw."{table}" AS SELECT {casts}, CAST(source_file AS VARCHAR) AS source_file, source_row FROM frame')
            counts[f"raw.{table}"] = len(frame["source_row"])
        for name, types in TRUTH_TYPES.items():
            path = (data_dir / "truth" / f"{name}.csv").as_posix()
            columns = "{" + ", ".join(f"'{c}': '{t}'" for c, t in types.items()) + "}"
            select = "* REPLACE (CAST(line_ids AS JSON)::VARCHAR[] AS line_ids)" if name == "discrepancies" else "*"
            con.execute(
                f"CREATE TABLE truth.{name} AS SELECT {select} FROM read_csv('{path}', header = true, "
                f"columns = {columns}, quote = '\"', escape = '\"')"
            )
            counts[f"truth.{name}"] = con.execute(f"SELECT count(*) FROM truth.{name}").fetchone()[0]
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data")
    parser.add_argument("--db", default="warehouse/fees.duckdb")
    args = parser.parse_args(argv)
    if not (Path(args.data) / "raw").is_dir():
        print(f"no raw data under {args.data}/raw; run `make data`", file=sys.stderr)
        return 1
    counts = load(args.data, args.db)
    width = max(len(t) for t in counts)
    for table, n in counts.items():
        print(f"{table:<{width}}  {n:>9,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
