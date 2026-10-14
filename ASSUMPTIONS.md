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

## A21 Markup lines that read as two errors

- **Default:** a markup line whose billed amount equals both the previous contract version's rate for the same tier (`stale_rate`) and the first tier's rate (`retroactive_tier_not_applied`) takes the reading that the provider × month's unambiguous markup lines show more often; on a tie it is `stale_rate`.
- **Why:** on small payments the two rates round to the same cent; the month shows which error the provider made (a stale rate after an amendment, or a tier applied only from the threshold).
- **Alternatives:** always prefer one type; report such lines as `fee_mismatch`.
- **Set in:** `dbt/models/intermediate/int_charge_comparison.sql`.

## A22 Reference date for dispute deadlines

- **Default:** `days_left` counts from the dbt var `as_of_date`, default `2026-07-15` (two weeks after the synthetic period ends), not from the run date.
- **Why:** the build must reproduce the same numbers on any day; the date is just late enough that the last invoices are open and the early ones have expired.
- **Alternatives:** the run date (`current_date`), which changes every number in M07 daily.
- **Set in:** `vars.as_of_date` in `dbt/dbt_project.yml`; override with `dbt build --vars '{as_of_date: 2026-08-01}'`.

## A23 Provider comparison

- **Default:** every succeeded card payment is priced under each card contract version in force at its time: payment-level fees only (interchange and scheme fee, markup and fixed fee; or the blended rate), the markup tier taken from that provider's actual month volume. Refund and chargeback fees, minimums and volume discounts are left out; months are UTC.
- **Why:** answers "what would this volume have cost there" with the terms that scale with volume, without simulating how moving volume would change the other provider's tiers.
- **Alternatives:** re-tiering the alternative with the moved volume; including refund, chargeback and monthly terms.
- **Set in:** `dbt/models/marts/fct_provider_comparison.sql`.

## A24 Invoice a finding is disputed on

- **Default:** a finding belongs to the invoice of the statement its line arrived in (a late line, N04, goes with the next month's invoice); a charge with no line of its own (a missing markup credit) to the statement of the event's other lines; a provider × month finding to that month's invoice. The dispute deadline is that invoice's date plus the contract's `dispute_window_days`.
- **Why:** the dispute window starts with the invoice that billed (or should have billed) the charge.
- **Alternatives:** the invoice of the event month regardless of where the line arrived.
- **Set in:** `dbt/models/intermediate/int_charge_comparison.sql`, `dbt/models/marts/fct_findings.sql`.

## A30 Every client invoice month is checked

- **Default:** client billing is checked for every month, the last period month included; no client finding is pending.
- **Why:** Fernway builds its client invoices from the same ledger export the checks read (A12), so the last month's invoice already excludes the lag day and the ledger fully covers what it bills, month-level terms (volume tier, promotion, platform fee) included.
- **Alternatives:** treat month-level client checks of a month the ledger does not fully cover as pending, as for provider months (A19); that would hold back real leakage in the last month.
- **Set in:** `dbt/models/intermediate/int_expected_client_billing.sql`, `int_client_billing_comparison.sql`.

## A31 Client findings are corrected, not disputed

- **Default:** a client finding belongs to Fernway's invoice for that client × month. Its `dispute_deadline` is the invoice date plus the agreement's `dispute_window_days`: the period in which the invoice is open to query and Fernway issues a correction. Most client findings are revenue leakage (billed too little), which Fernway recovers by invoicing the difference.
- **Why:** these are Fernway's own invoices; there is no provider to dispute with, but the agreement's window is the natural deadline for correcting them.
- **Alternatives:** no deadline (leave the columns null); the provider-side dispute queue (not applicable to Fernway's own invoices).
- **Set in:** `dbt/models/marts/fct_client_billing_findings.sql`; `dispute_window_days` in `contracts/clients/*.yml`.

## A32 Client margin: which costs, which month

- **Default:** a client's provider costs are the invoiced provider fees of its ledger events (payouts by execution), by UTC month; a line without a ledger event goes to the client the provider reported. Monthly charges without an event are split by volume share in the provider's month (A09): the monthly minimum by processed volume, the volume adjustment by EEA consumer volume (the volume each term is computed on), in whole cents with largest remainders. The FX spread (M08) of the client's payouts is a cost too, since the client FX markup is priced to cover it. Fees on lines after the ledger watermark are shown as pending and kept out of the month's margin, because the lag day is billed to clients in the next cycle (A12).
- **Why:** revenue and costs then cover the same events; event-level costs are traceable, and the volume a monthly term is computed on is the fairest key for that term.
- **Alternatives:** fees only, without the FX spread; one volume key for every monthly charge; include the lag day's fees in the last month's margin.
- **Set in:** `dbt/models/intermediate/int_provider_cost_allocation.sql`, `dbt/models/marts/fct_client_margin.sql`.

## A33 Client leakage rules

- **Default:** a client invoice line (client × month × component) that differs from the agreement by at least one minor unit is `rail_not_billed` when a payout rail with expected fees has no line, `fx_markup_not_billed` when expected FX markup has no line, `promo_after_end_date` when the billed promotional discount equals the promotion applied to the whole month and the promotion ended before the month's last day, `volume_discount_too_high` when the billed volume discount equals the discount of a higher tier than the month's volume earns, `rounding` for a one-unit difference that the other rounding mode explains, and `fee_mismatch` otherwise.
- **Why:** each rule names the billing error a finance team would fix, and requiring the billed amount to match the error pattern keeps every other difference visible as `fee_mismatch`.
- **Alternatives:** classify by component only (any missing or larger discount is the matching leakage type).
- **Set in:** `dbt/models/intermediate/int_client_billing_comparison.sql`.
