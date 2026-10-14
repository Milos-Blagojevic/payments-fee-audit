# Assumptions

Numbered and stable: code, docs and findings cite these ids. Each entry gives the assumption, the default, why, the alternatives and where it is set.

## A01 Base currency and FX for reporting

- **Default:** EUR. Amounts in other currencies are converted at the hourly mid rate of the event hour.
- **Why:** Fernway and every provider bill in EUR; one base currency keeps totals comparable.
- **Alternatives:** daily reference rates; the provider's applied rate.
- **Set in:** `docs/data-contract.md` section 1; `fx__mid_hourly`.

## A02 Month boundaries for tiers and minimums

- **Default:** the contract's time zone: Northgate `Europe/Berlin`, all others `UTC`.
- **Why:** volume tiers and minimums are defined on the provider's calendar month, which is the one its contract states.
- **Alternatives:** UTC months for everyone (simpler, but wrong around midnight at month end for Northgate).
- **Set in:** `timezone` in each contract YAML; `docs/data-contract.md` section 1.

## A03 Contract version for an event

- **Default:** the version whose `[effective_from, next effective_from)` contains the event timestamp in the contract's time zone.
- **Why:** amendments apply from a date, and the event timestamp is what the provider prices.
- **Alternatives:** the version in force at the statement or invoice date.
- **Set in:** `effective_from` in each contract YAML; `feeaudit/contracts.py` derives `effective_to` and checks that versions are contiguous.

## A04 Rounding

- **Default:** exactly as each contract states (`half_up` or `half_even`, per transaction or per invoice line). A one-minor-unit difference that the other rounding mode explains is reported as `rounding`, not as an overcharge.
- **Why:** rounding is a contract term; ties rounded the other way are a nuisance, not a billing error.
- **Alternatives:** a tolerance of a few cents per line, which would hide small systematic errors.
- **Set in:** `rounding` in each contract YAML; `docs/data-contract.md` section 1.

## A05 Finding threshold

- **Default:** one minor unit after the contract's rounding.
- **Why:** every cent is traceable; anything smaller is not money.
- **Alternatives:** a materiality threshold per provider.
- **Set in:** `docs/data-contract.md` section 5.

## A06 Matching

- **Default:** provider reference first; for lines without one, a fallback on amount, currency, a ±48 h window and client, one-to-one, among ledger events not matched by reference.
- **Why:** about 2% of provider lines have no reference (N06); amount, time and client are what a person would use.
- **Alternatives:** fuzzy scoring, or leaving such lines unmatched.
- **Set in:** `docs/data-contract.md` section 6. The generator removes the reference only where that fallback key is unambiguous.

## A07 Interchange and scheme fee reference

- **Default:** an illustrative, versioned table keyed by scheme × card type × region (`dbt/seeds/interchange_table_v1.csv`).
- **Why:** real scheme tables are not public in a usable form and are not needed to show the method.
- **Alternatives:** published regulated caps for EEA consumer cards; per-issuer tables.
- **Set in:** `dbt/seeds/interchange_table_v1.csv`.

## A08 FX benchmark

- **Default:** a synthetic hourly mid series per pair (seeded random walk) stands in for a published reference rate.
- **Why:** the build must run offline and reproducibly.
- **Alternatives:** a published daily reference rate, or market data at minute resolution.
- **Set in:** `fx` in `config/generator.yml`.

## A09 Cost allocation to clients

- **Default:** provider costs are allocated by the event they belong to; costs with no event (monthly minimums, volume adjustments) by volume share.
- **Why:** event-level costs are traceable; volume share is the plainest split of the rest.
- **Alternatives:** by transaction count, or not allocated.
- **Set in:** the client margin model (spec section 9).

## A10 Anomaly model

- **Default:** robust z-score of the daily effective rate per provider, fee component and card segment against a 28-day rolling median (MAD), threshold 4.
- **Why:** explainable in one sentence and resistant to the outliers it is looking for.
- **Alternatives:** seasonal decomposition; isolation forests (harder to explain).
- **Set in:** the anomaly detection model (spec section 10).

## A11 All card payments are in EUR

- **Default:** every card payment, refund and chargeback is in EUR; only payouts use other currencies.
- **Why:** Fernway's marketplaces sell in EUR; FX lives where it costs money, in payouts.
- **Alternatives:** multi-currency acquiring with per-currency interchange.
- **Set in:** `docs/data-contract.md` section 1; `generator/ledger.py`.

## A12 Client invoices are built from the ledger export

- **Default:** Fernway bills its clients from the events in the ledger export, by UTC month (payments by `created_at`, payouts by `executed_at`). The last period month therefore excludes the lag day, which is billed in the next cycle.
- **Why:** billing runs on the same internal data the checks use, so a client finding is never caused by the ledger lag.
- **Alternatives:** bill from the complete event stream and treat the lag day as pending in the checks.
- **Set in:** `generator/client_billing.py`; `docs/data-contract.md` section 8.5.

## A13 Payouts are dated by execution

- **Default:** `executed_at` selects a payout's contract version, statement month, FX hour and client billing month; the Elixir rail is used only for payouts executed from 2026-04-01.
- **Why:** the provider prices and converts at execution.
- **Alternatives:** the creation timestamp (the payout instruction).
- **Set in:** `generator/billing.py`, `generator/ledger.py`; `docs/data-contract.md` section 8.3.

## A14 Bases of the client FX markup and discounts

- **Default:** the FX markup is charged on `E = round(amount_minor / mid)` per non-EUR payout (mid at the execution hour), summed and rounded once. Volume and promotional discounts are percentages of the unrounded payment-fee sum, both on the gross fees (they do not compound). A promotion covers payments created up to and including its `valid_until` UTC date.
- **Why:** these are the readings closest to the agreement wording and to how the provider SWIFT fee converts to EUR.
- **Alternatives:** the exact EUR equivalent without per-payout rounding; discounts on the rounded fee line; compounding discounts.
- **Set in:** `generator/client_billing.py`; `docs/data-contract.md` section 8.5.

## A15 Synthetic volumes and mixes

- **Default:** 400k payment attempts (94% succeeded) over 40 clients, lognormal amounts per client (median about EUR 54, with price points such as x.00, x.50 and x.99), monthly seasonality rising from January to June, three mid-period provider switches, 3% refunds 1–30 days later, 0.3% chargebacks 20–90 days later, 60k payouts with about 1% of SWIFT payouts above EUR 45k.
- **Why:** these values put every calibration target of spec section 7.8 in range for the default seed, and the threshold crossings that the planted cases need (Northgate above and below EUR 2.5M, Brightpay EEA consumer volume above EUR 1.5M) happen with a margin that the one-day ledger lag cannot flip; the generator asserts that margin.
- **Alternatives:** any other mix; the calibration table shows whether it still exercises every case.
- **Set in:** `config/generator.yml`.

## A16 Kestrel's normal FX spread

- **Default:** a spread drawn per payout between 50% and 90% of the contract cap, applied to the mid of the execution hour and quoted with 6 decimals.
- **Why:** providers price close to, but below, a contractual cap; a margin below the cap keeps rate quoting from crossing it.
- **Alternatives:** a fixed spread per currency.
- **Set in:** `fx.kestrel_spread_share_of_cap` in `config/generator.yml`.

## A17 Events after the last statement month

- **Default:** events in a provider month that starts after the period (Northgate payments from 2026-06-30 22:00 UTC, already July in Berlin) are not billed yet and appear in no statement.
- **Why:** a provider bills a month after it closes.
- **Alternatives:** a partial July statement.
- **Set in:** `generator/billing.py`; `docs/data-contract.md` section 8.

## A18 Provider fees in the calibration

- **Default:** provider fees are the billed card fees (net of credits and adjustments), the Kestrel payout fees and the Kestrel FX spread cost (EUR debited minus the EUR equivalent at mid). Planted overcharges are the positive differences of D01–D14.
- **Why:** the spread is a real cost of the payout provider and D11/D12 overcharges sit in it.
- **Alternatives:** fees only, excluding FX.
- **Set in:** `generator/calibration.py`.

## A19 Ledger watermark and pending lines

- **Default:** the ledger is complete for every event before 00:00 UTC of its latest export date (the file for export date D holds the events of D − 1). A provider line for an event at or after that time with no ledger match is `unmatched_pending`, not an unknown charge; a ledger event in a provider month after the provider's last statement is `ledger_only` with reason `not_billed_yet`.
- **Why:** the ledger export lags a day (N07); a line the ledger cannot have yet is not evidence of a phantom charge.
- **Alternatives:** the latest event timestamp in the ledger (depends on traffic at the end of the day); a fixed cut-off date in configuration.
- **Set in:** `dbt/models/intermediate/int_ledger_watermark.sql`, `int_reconciliation.sql`.

## A20 Reconciliation tie-breaks

- **Default:** when several lines carry the same event reference and component, the first by statement month, then line id, is the match and every other one is a `duplicate` (D06). A fallback pair is kept only when the line and the ledger event × component are each other's closest candidate in time (ties by event id, then line id); a line with no such partner stays unmatched.
- **Why:** deterministic, one-to-one, and the provider's own numbering puts the original before a re-billed copy.
- **Alternatives:** an optimal assignment (Hungarian matching) over the fallback candidates; flagging every line of a duplicated event.
- **Set in:** `dbt/models/intermediate/int_reconciliation.sql`.
