"""`python -m feeaudit.extraction extract [--only NAME]` calls the Anthropic API (paid, needs ANTHROPIC_API_KEY and
requirements-llm.txt); `python -m feeaudit.extraction score` scores the committed extractions (offline, CI-safe)."""

import argparse
import os
import sys
from pathlib import Path

from feeaudit.extraction.budget import CONFIG_PATH, BudgetError, load_config, usd
from feeaudit.extraction.extract import OUT_DIR, TEXT_DIR, ExtractionError, extract
from feeaudit.extraction.score import report, score, write_scores


def _client():
    try:
        import anthropic
    except ImportError:
        raise ExtractionError("the anthropic SDK is not installed: pip install -r requirements-llm.txt") from None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ExtractionError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def run_extract(args):
    config = load_config(args.config)
    names = sorted(p.stem for p in args.text_dir.glob("*.md"))
    if args.only:
        if args.only not in names:
            print(f"unknown contract text {args.only!r}; choose from {', '.join(names)}", file=sys.stderr)
            return 1
        names = [args.only]
    try:
        config.prices_for(config.model())  # refuse before needing a key or the SDK
        client = _client()
        for name in names:
            result = extract(name, client, config, args.text_dir, args.out_dir)
            u = result["usage"]
            print(
                f"{name}: {result['path']} ({u['input_tokens']} input + {u['output_tokens']} output tokens, "
                f"USD {usd(result['cost_usd'])}; total spent USD {result['total_usd']})"
            )
            for problem in result["validation_errors"]:
                print(f"  schema: {problem}")
    except (BudgetError, ExtractionError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def run_score(args):
    rows, versions = score(args.providers_dir, args.extracted_dir)
    write_scores(rows, args.db)
    print("\n".join(report(versions)))
    print(f"\n{len(rows)} field rows written to evaluation.extraction_scores in {args.db}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m feeaudit.extraction", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    ext = commands.add_parser("extract", help="extract contract YAML from contracts/text with the Anthropic API (paid)")
    ext.add_argument("--only", metavar="NAME", help="one contract version, e.g. northgate-v2")
    ext.add_argument("--config", type=Path, default=CONFIG_PATH)
    ext.add_argument("--text-dir", type=Path, default=TEXT_DIR)
    ext.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ext.set_defaults(run=run_extract)
    sc = commands.add_parser("score", help="score contracts/extracted against contracts/providers (offline)")
    sc.add_argument("--providers-dir", type=Path, default=Path("contracts/providers"))
    sc.add_argument("--extracted-dir", type=Path, default=OUT_DIR)
    sc.add_argument("--db", type=Path, default=Path("warehouse/fees.duckdb"))
    sc.set_defaults(run=run_score)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
