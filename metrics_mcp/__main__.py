"""`python -m metrics_mcp serve` (MCP over stdio) and `python -m metrics_mcp lock --check | --update`."""

import argparse
import os
import sys

from metrics_mcp import lock
from metrics_mcp.catalog import ROOT, Catalog, Paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m metrics_mcp", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the MCP server on stdio")
    lock_parser = commands.add_parser("lock", help="check or update metrics.lock.yml")
    mode = lock_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail if the lock does not match the definitions")
    mode.add_argument("--update", action="store_true", help="rewrite the lock after a version bump")
    args = parser.parse_args(argv)

    if args.command == "serve":
        os.chdir(ROOT)  # dbt/profiles.yml points at warehouse/fees.duckdb relative to the repository root
        from metrics_mcp.server import build

        build().run("stdio")
        return 0

    paths = Paths.at()
    try:
        catalog = Catalog.load(paths)
    except FileNotFoundError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    if args.check:
        problems = lock.check(catalog, paths.lock)
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"OK: {len(catalog.metrics)} metrics match {paths.lock.name}")
        return 0
    problems = lock.update(catalog, paths.lock)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"wrote {paths.lock.name}: " + ", ".join(f"{i} v{m.version}" for i, m in sorted(catalog.metrics.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
