# payments-fee-audit

Checks every fee a payments company pays its providers, and every invoice it sends its own clients, against the contracts behind them. Runs on fully synthetic, seeded data, so every planted billing error is known and the checks can be scored.

Work in progress.

## Reproduce

Requires Python 3.12.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
make all
```

## Report site

An [Evidence](https://evidence.dev) site in `site/` presents the findings, dispute queue, provider costs, provider comparison, FX conversions and evaluation from the warehouse. Requires Node.js 20 or later and a warehouse built by `make all`.

```bash
make site                 # npm ci, extract the marts to site/sources, build the static site into site/build
cd site && npm run preview  # serve the build locally; or `npm run dev` for live editing
```

## Pinned versions

| Package | Version |
|---|---|
| dbt-core | 1.12.5 |
| dbt-duckdb | 1.11.0 |
| duckdb | 1.5.6 |
| @evidence-dev/evidence | 40.1.8 |
| @evidence-dev/core-components | 5.4.2 |
| @evidence-dev/duckdb | 2.0.1 |
| @duckdb/node-api | 1.5.6-r.1 |

The full lock is in `requirements.txt` and `requirements-dev.txt`, and for the site in `site/package-lock.json`.
