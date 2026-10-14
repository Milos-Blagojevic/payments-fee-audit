# Metrics

One definition per metric, implemented once. Reports and the README read these columns; they never recompute them. Money is in minor units (EUR cents) unless stated.

| Id | Metric | Definition | Unit | Grain | Implemented in |
|---|---|---|---|---|---|
| M01 | Processed volume | Sum of succeeded card payment amounts in the ledger, by event date in UTC | EUR minor units | provider × month × card segment | `fct_provider_costs.volume_minor` |
| M02 | Provider fees | Sum of billed provider charges, net of credits (refund markup credits, volume adjustments); FX debits are not fees | EUR minor units | provider × month × component × card segment | `fct_provider_costs.billed_minor` |
| M03 | Effective rate | M02 ÷ M01 | basis points | provider × month × component × card segment | `fct_provider_costs.effective_rate_bps` |
| M04 | Markup rate | Acquirer markup ÷ M01 (interchange++ provider only) | basis points | provider × month × card segment | `fct_provider_costs.effective_rate_bps` on `component = 'markup'` rows |
| M05 | Overcharge | Sum of positive `difference_minor` of rule findings, excluding `rounding` | EUR minor units | provider invoice | `fct_dispute_queue.overcharge_minor` |
| M06 | Undercharge | Sum of negative `difference_minor` of rule findings, excluding `rounding` (the provider billed too little; reported, never disputed) | EUR minor units | provider invoice | `fct_dispute_queue.undercharge_minor` |
| M07 | Recoverable | M05 for findings whose dispute deadline is on or after the `as_of_date` var (A22) | EUR minor units | provider invoice | `fct_dispute_queue.recoverable_minor` |
| M08 | FX spread cost | EUR debited − EUR equivalent at the execution-hour mid | EUR minor units | payout | `fct_fx_conversions.spread_cost_minor` |

M09 (revenue leakage) and M10 (client margin) arrive with the client billing models.
