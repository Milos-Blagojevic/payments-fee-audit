# Metrics

One definition per metric, implemented once. Reports and the README read the mart columns behind these metrics; they never recompute them. Money is in minor units (EUR cents) unless stated.

The definitions are the MetricFlow semantic models and metrics in `dbt/models/semantic/_semantic.yml`. The table below is generated from them by `make report` (from `dbt/target/semantic_manifest.json`), and the metrics MCP server (`python -m metrics_mcp serve`, see the README) serves exactly these definitions, so the document cannot drift from what agents get. "Group by" lists what MetricFlow allows for the metric; ratios (M03, M04) are ratios of sums at the requested grain, never averages of row rates.

<!-- generated:metrics -->
| Id | Metric | Definition | Computed as | Unit | Version | Group by | Checks |
|---|---|---|---|---|---|---|---|
| M01 | Processed volume (`processed_volume`) | Sum of succeeded card payment amounts in the ledger, by event date in UTC. | sum(`fct_processed_volume.volume_minor`) | EUR minor units | 1 | `card_segment`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests |
| M02 | Provider fees (`provider_fees`) | Sum of billed provider charges, net of credits (refund markup credits, volume adjustments); FX debits are not fees. | sum(`fct_provider_costs.billed_minor`) | EUR minor units | 1 | `card_segment`, `metric_time`, `provider`, `provider__pricing_model`, `provider_cost__component` | certified, lock, dbt_tests |
| M03 | Effective rate (`effective_rate`) | M02 ÷ M01, a ratio of sums at the requested grain (never an average of row rates). | M02 ÷ M01 | bps | 1 | `card_segment`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests |
| M04 | Markup rate (`markup_rate`) | Billed acquirer markup ÷ M01, for providers on interchange++ pricing only; a ratio of sums at the requested grain. | M02 where `component = 'markup'` ÷ M01, where `pricing_model = 'interchange_plus_plus'` | bps | 1 | `card_segment`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests |
| M05 | Overcharge (`overcharge`) | Sum of positive `difference_minor` of rule findings, excluding `rounding`. | sum(`fct_dispute_queue.overcharge_minor`) | EUR minor units | 1 | `dispute_queue_item__status`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests, differential |
| M06 | Undercharge (`undercharge`) | Sum of negative `difference_minor` of rule findings, excluding `rounding` (the provider billed too little; reported, never disputed). | sum(`fct_dispute_queue.undercharge_minor`) | EUR minor units | 1 | `dispute_queue_item__status`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests, differential |
| M07 | Recoverable (`recoverable`) | M05 for findings whose dispute deadline is on or after the `as_of_date` var (A22). | sum(`fct_dispute_queue.recoverable_minor`) | EUR minor units | 1 | `dispute_queue_item__status`, `metric_time`, `provider`, `provider__pricing_model` | certified, lock, dbt_tests, differential |
| M08 | FX spread cost (`fx_spread_cost`) | EUR debited − EUR equivalent at the execution-hour mid. | sum(`fct_fx_conversions.spread_cost_minor`) | EUR minor units | 1 | `client`, `metric_time`, `payout__currency`, `payout__rail` | certified, lock, dbt_tests, differential |
| M09 | Revenue leakage (`revenue_leakage`) | Expected client billing under the pricing agreement − actual client billing (invoice lines, net of discounts); positive = Fernway billed too little. | sum(`fct_client_margin.revenue_leakage_minor`) | EUR minor units | 1 | `client`, `metric_time` | certified, lock, dbt_tests |
| M10 | Client margin (`client_margin`) | Actual client billing − provider fees allocated to the client's events (monthly charges by volume share, A09, A32) − M08 of the client's payouts. | sum(`fct_client_margin.margin_minor`) | EUR minor units | 1 | `client`, `metric_time` | certified, lock, dbt_tests, differential |
<!-- /generated -->

## Checks

The server evaluates a metric's checks on every query; any failure is a refusal with the reason and the fix, never a number (A54).

| Check | Passes when | Required by |
|---|---|---|
| `certified` | `meta.certified` is `true`; drafts are neither listed nor queryable | every metric |
| `lock` | the running definition's fingerprint equals `metrics.lock.yml` for the current version (A50, A51) | every metric |
| `dbt_tests` | every dbt data and unit test on the metric's backing models and their upstream nodes passed in the last `dbt build` (`dbt/target/run_results.json`); a missing result fails (A53) | every metric |
| `differential` | the last `make verify` passed, after the last build: the Python reference engine computes the same expected charges as `int_expected_charges` | M05, M06, M07, M08, M10 |

Why `differential` for those five (A52): M05–M07 are billed − expected over the rule findings, so a wrong expected charge is a wrong number; M08 measures the spread against the EUR equivalent at mid that `int_expected_charges` computes for each payout; M10 subtracts M08. M01–M04 are billed fees and processed volume, which do not depend on expected charges, and M09 compares client billing with `int_expected_client_billing`, which the differential check does not cover.
