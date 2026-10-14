# payments-fee-audit

Checks every fee a payments company pays its providers, and every invoice it sends its own clients, against the contracts behind them. Runs on fully synthetic, seeded data, so every planted billing error is known and the checks can be scored.

Work in progress.

## Reproduce

Requires Python 3.12.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
make all
```

## Pinned versions

| Package | Version |
|---|---|
| dbt-core | 1.12.5 |
| dbt-duckdb | 1.11.0 |
| duckdb | 1.5.6 |

The full lock is in `requirements.txt` and `requirements-dev.txt`.
