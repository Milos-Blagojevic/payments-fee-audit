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

- **Default:** robust z-score of the daily effective rate per provider, fee component and card segment (billed amount of the day's card events in basis points of that day's processed volume, M01 by UTC day) against the median of the previous 28 days: z = 0.6745 × (rate − median) ÷ MAD; flagged when |z| > 4. A day is scored once its window holds 28 data points; the MAD = 0 case is A42. Payout fees (no card segment, no card volume) are covered by the new-component check only (A43).
- **Why:** explainable in one sentence and resistant to the outliers it is looking for.
- **Alternatives:** seasonal decomposition; isolation forests (harder to explain); a rate per payment count instead of per volume.
- **Set in:** dbt vars `anomaly_window_days` and `anomaly_z_threshold` (`dbt/dbt_project.yml`); `dbt/models/intermediate/int_daily_component_rates.sql`.

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

## A40 Northgate line types the data contract does not list

- **Default:** an unlisted Northgate `line_type` is a fee component of its own (its lower-case name); the line is month-level when it carries a `period`, otherwise a charge on the payment the row describes, matched to the ledger like the payment's other lines.
- **Why:** a provider can start billing a new fee type at any time; the engine must reconcile and count it rather than drop it or fail the build.
- **Alternatives:** read the event type from the reference prefix (`pay_`, `ref_`, `cb_`); reject unknown line types in staging.
- **Set in:** `dbt/models/intermediate/int_provider_lines.sql`.

## A41 Components no contract names are outside the rules

- **Default:** a billed component that no version of the provider's contract names gets no rule classification: not `fee_mismatch`, and not `unknown_charge` when its event is in the ledger (a line of an event missing from the ledger is still `unknown_charge`). It is reconciled, matched and counted in `fct_provider_costs` (expected 0) like any other line; the anomaly model judges it.
- **Why:** the rules compare billed amounts with contract terms; a charge no term describes is the case anomaly detection exists for, and calling it a mismatch of a term that does not exist would misstate the clause.
- **Alternatives:** report every such line as `fee_mismatch`; a dedicated rule type for charges without a clause.
- **Set in:** `dbt/models/intermediate/int_charge_comparison.sql` (`component_has_term`).

## A42 Robust z-score when the MAD is 0

- **Default:** when at least half of the window's rates equal the median (MAD = 0), z = (rate − median) ÷ (1.2533 × mean absolute deviation from the median); when that is also 0 the baseline is constant and any other rate is flagged (z is null).
- **Why:** sparse series (chargeback fees on a small card segment, most days 0) have MAD = 0; dividing by it would flag every non-zero day. The mean-absolute-deviation fallback is the usual companion of the MAD score (1.2533 makes both consistent with a normal standard deviation).
- **Alternatives:** skip days with MAD = 0; add a floor to the MAD; flag any deviation from the median.
- **Set in:** `dbt/models/intermediate/int_daily_component_rates.sql`.

## A43 New fee component

- **Default:** a `new_component` anomaly on the first day (event date, UTC) a provider bills a component that no version of its contract names, provided the provider has at least `anomaly_window_days` (28) days of billing history before it. Card segment `all`; baseline 0 bps.
- **Why:** "never seen before" needs history; components the contract names are known to the engine even before they are first billed (a first chargeback fee, a minimum in its first month).
- **Alternatives:** flag every component first billed after the first statement month, named or not; one anomaly per card segment.
- **Set in:** `dbt/models/marts/fct_anomalies.sql`.

## A44 Anomalies that become findings

- **Default:** an anomaly is explained by rule findings when all of the day's money beyond the contract belongs to charges a rule classifies, and by the contract when every charge of the day equals its expected amount (a new tier, contract version or card mix); only unexplained anomalies become findings (`method = 'anomaly'` in `fct_findings`), one per provider × component × card segment × day, with the day's unexplained lines, the baseline rate's amount as expected (0 for a new component) and the contract version in force. They are not disputed (`fct_dispute_queue` and `fct_invoice_reconciliation` count rule findings only) and the evaluation does not score them.
- **Why:** a rate shift the contract or a rule already accounts for needs no second finding; an anomaly is a lead to investigate, not a claim with a clause behind it.
- **Alternatives:** a finding for every flagged day; one finding per anomaly episode instead of per day.
- **Set in:** `dbt/models/marts/fct_anomalies.sql`, `dbt/models/marts/fct_findings.sql`.

## A50 What a metric's fingerprint covers

- **Default:** a stable hash (SHA-256 of canonical JSON, first 16 hex digits) of the metric's resolved definition in `dbt/target/semantic_manifest.json`: its spec and filters, the specs of its input metrics, the measures it uses, the entities, dimensions, defaults and node relation of their semantic models and of the semantic models those join to (`providers` for every provider metric), the `unit` in its meta, and the SQL checksum (`manifest.json`) of every dbt model behind those semantic models. Descriptions, labels and the rest of `meta` (owner, `certified`, `requires`, the version itself) are left out.
- **Why:** everything that can change a served number, the allowed dimensions or the unit changes the fingerprint; editing prose or ownership does not force a new version.
- **Alternatives:** include the SQL of every upstream model, which would version all ten metrics on any staging change; hash the YAML file, which versions every metric on any edit. Upstream changes are covered by the `dbt_tests` and `differential` checks instead (A52). An upgrade of dbt or MetricFlow that serialises the spec differently changes fingerprints too, and is reviewed like a definition change.
- **Set in:** `metrics_mcp/catalog.py`.

## A51 One live version per metric

- **Default:** each metric's `meta.version` starts at 1; `metrics.lock.yml` (committed) holds the version and fingerprint of every metric with a `metric_id`. `python -m metrics_mcp lock --check` (in `make all`) fails when a fingerprint changed but the version did not ("bump the version"), when the version moved but the lock did not ("run lock --update"), when a version skips, and when a metric is missing from or extra in the lock. `lock --update` rewrites the lock and accepts a changed definition only at the locked version + 1. The server serves only the current version; `query_metric` with another `expected_version` is refused (`stale_version`).
- **Why:** an agent's cached understanding of a metric must never silently mean something else; one live version keeps the server and the doc simple.
- **Alternatives:** serve old versions side by side (needs old definitions and old data kept queryable); semantic versioning with compatible changes.
- **Set in:** `metrics_mcp/lock.py`, `metrics.lock.yml`, `Makefile` (`metrics-lock`).

## A52 Which checks each metric requires

- **Default:** every metric requires `certified`, `lock` and `dbt_tests` (the server evaluates these three even if `meta.requires` omits one, and `lock --check` fails on such a definition). `differential` is required by M05, M06, M07 (billed − expected over rule findings), M08 (the spread is measured against the EUR equivalent at mid from `int_expected_charges`) and M10 (subtracts M08). M01–M04 are billed fees and volume, and M09 compares client billing with `int_expected_client_billing`, which the differential check does not cover. A metric's backing models are the dbt models of its measures' semantic models and of the semantic models they join to.
- **Why:** a check belongs where its failure would make the number wrong; requiring `differential` everywhere would refuse the volume when only the expected charges are in doubt.
- **Alternatives:** require every check for every metric; derive `differential` from lineage (every provider metric reads `int_charge_comparison`, which joins the expected charges, so lineage alone would require it for M02 too).
- **Set in:** `meta.requires` in `dbt/models/semantic/_semantic.yml`; `metrics_mcp/checks.py`; `METRICS.md`.

## A53 dbt tests a metric depends on

- **Default:** every dbt data or unit test whose `depends_on` touches a backing model of the metric or any node upstream of it (models, seeds, sources) must have status `pass` in `dbt/target/run_results.json`; `warn`, `fail`, `error`, `skipped` or a missing result fails the check. `differential` additionally requires the last `make verify` (recorded in `verification.check_results`) to have run after the last build.
- **Why:** a failing test anywhere upstream can mean a wrong number; a test that did not run proves nothing.
- **Alternatives:** only the tests on the backing model itself; accept `warn`.
- **Set in:** `metrics_mcp/checks.py`, `metrics_mcp/catalog.py` (`tests_for`), `feeaudit/verify.py` (`record`).

## A54 Refusal policy

- **Default:** fail closed. The server answers only when the metric is certified, the request is valid and every required check passes; otherwise it returns `status: refused` with a reason (`unknown_metric`, `not_certified`, `stale_version`, `invalid_request`, `check_failed`), the failed checks with their details, and the fix, and no number. An unexpected error returns `status: error`, also without a number. Every call, answered or not, is appended to `warehouse/metrics_mcp_audit.jsonl`.
- **Why:** an agent that receives a number repeats it; a number that failed a check is worse than none.
- **Alternatives:** answer with a warning attached (agents drop warnings); serve the last good result (needs a result cache and staleness rules).
- **Set in:** `metrics_mcp/service.py`.

## A55 No freshness check

- **Default:** the server does not refuse because the data is old.
- **Why:** the data is a closed synthetic period (January to June 2026) and `as_of_date` is a fixed dbt var (A22), so age says nothing about correctness; every answer states `as_of_date` and `built_at`, and `differential` already refuses a verification older than the build.
- **Alternatives:** refuse when the last build or the ledger watermark is older than a threshold, which a deployment on live data would need.
- **Set in:** `metrics_mcp/checks.py` (absence of such a check).

## A56 What agents may send

- **Default:** a metric id, `group_by` names and filters `{dimension, op, value}`, nothing else. Names must be in MetricFlow's allowed group-by set for the metric (foreign entities such as `provider`, categorical dimensions such as `provider_cost__component`, and `metric_time` at a grain from `time_grain`); row-level primary entities are not offered. Operators: `eq`, `ne`, `in`, `not_in` on every dimension, plus `gt`, `gte`, `lt`, `lte` on `metric_time`. Values are strings of letters, digits, space and `_ . : @ -` (at most 64, at most 100 in a list), or ISO dates for `metric_time`; they are quoted again before MetricFlow builds its where clause. `limit` is 1 to 10,000 (default 1,000) and a response says when it was truncated.
- **Why:** structured requests leave no room for SQL or template injection while covering the questions finance asks of these metrics.
- **Alternatives:** accept MetricFlow where-clause strings (an SQL surface); bind parameters (the dbt adapter does not support them).
- **Set in:** `metrics_mcp/service.py`.

## A57 Basis points from MetricFlow ratios

- **Default:** M03 and M04 are MetricFlow ratio metrics, so the ratio of sums is computed by MetricFlow, in DOUBLE; the server multiplies it by 10,000 and rounds half up to 4 decimal places, the scale of `effective_rate_bps` in the marts, and returns a decimal string. A ratio with no denominator (payout fees grouped by card segment, a provider without card volume) is `null`.
- **Why:** MetricFlow renders a ratio as `CAST(numerator AS DOUBLE) / CAST(NULLIF(denominator, 0) AS DOUBLE)`; a double carries about 16 significant digits, ample for 4 decimals of basis points, and the tests compare the result with the exact decimal ratio of the marts' sums.
- **Alternatives:** query numerator and denominator and divide in Python with exact decimals (then MetricFlow no longer computes the ratio); a derived metric with integer arithmetic in its expression.
- **Set in:** `metrics_mcp/service.py` (`_bps`).

## A58 Processed volume and pricing model for the semantic layer

- **Default:** M01 is served from `fct_processed_volume` (provider × UTC month × card segment), which `fct_provider_costs` now reads its volumes from; `fct_provider_costs.volume_minor` repeats the volume on every component row and cannot be summed. M04's denominator is restricted to providers whose contract has a tiered markup (`dim_providers.pricing_model = 'interchange_plus_plus'`). Provider and card segment are entities shared by the cost and volume semantic models, so M03 and M04 group by provider, card segment, pricing model and month, but not by fee component (volume has no component).
- **Why:** a ratio of sums needs each sum at its own grain; one volume table keeps M01 implemented once.
- **Alternatives:** a measure over `fct_provider_costs` with a "first row of the segment" flag; a hard-coded provider filter for M04.
- **Set in:** `dbt/models/marts/fct_processed_volume.sql`, `dbt/models/marts/dim_providers.sql`, `dbt/models/semantic/_semantic.yml`.
