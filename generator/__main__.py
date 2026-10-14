"""`python -m generator`: generate raw files and truth, load them, print the calibration table.

Exits 1 when a calibration target is out of range.
"""

import argparse
import sys
import time

from feeaudit.load import load
from generator.calibration import report
from generator.common import load_config
from generator.run import REPO, generate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(REPO / "config/generator.yml"))
    parser.add_argument("--out", default=str(REPO), help="directory that receives data/raw and data/truth")
    parser.add_argument("--db", default=str(REPO / "warehouse/fees.duckdb"), help="DuckDB file for schemas raw and truth")
    args = parser.parse_args(argv)
    start = time.time()
    g = generate(load_config(args.config), args.out)
    print(f"generated in {time.time() - start:.1f}s")
    counts = load(f"{args.out}/data", args.db)
    print(f"loaded {len(counts)} tables into {args.db} in {time.time() - start:.1f}s\n")
    width = max(len(t) for t in counts)
    for table, n in counts.items():
        print(f"{table:<{width}}  {n:>9,}")
    print()
    if not report(g):
        print("\ncalibration: some targets are out of range", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
