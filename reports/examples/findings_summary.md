# Findings summary

From 2026-01 to 2026-06, 18,230 provider charges differ from the contracts: EUR 17,251.23 overcharged and EUR 36.20 undercharged. As of 2026-07-15, EUR 4,320.13 can still be disputed on 5 open invoices (M07); EUR 12,931.10 is past its dispute deadline. A further 305 one-cent rounding differences (EUR 3.05 net) are reported but not disputed.

Amounts in EUR. An overcharge is billed above what the contract allows; an undercharge is billed below it (reported, never disputed). Recoverable means the invoice's dispute deadline is on or after 2026-07-15. Sources: `fct_findings`, `fct_dispute_queue`; the breakdown by provider, month and type is in `findings_summary.csv`.

## By type

| Type | Finding | Provider | Findings | Overcharge | Undercharge |
|---|---|---|---:|---:|---:|
| D01 | Markup at the rate before the amendment | Northgate Acquiring | 15,091 | 362.27 | 0.00 |
| D02 | Volume tier not applied to the whole month | Northgate Acquiring | 2 | 5,750.67 | 0.00 |
| D03 | Interchange or scheme fee above cost | Northgate Acquiring | 771 | 134.37 | 0.00 |
| D04 | Markup not credited on a refund | Northgate Acquiring | 538 | 138.69 | 0.00 |
| D05 | Monthly minimum charged when not due | Northgate Acquiring | 2 | 5,000.00 | 0.00 |
| D06 | Same payment charged twice | Brightpay | 271 | 413.82 | 0.00 |
| D07 | Card priced in the wrong segment | Brightpay | 474 | 623.94 | 0.00 |
| D08 | Fee on a declined or failed attempt | Brightpay | 196 | 298.21 | 0.00 |
| D09 | Chargeback fee above the contract | Brightpay | 93 | 465.00 | 0.00 |
| D10 | Volume discount not applied | Brightpay | 2 | 998.24 | 0.00 |
| D11 | FX spread above the cap | Kestrel Payouts | 263 | 1,083.56 | 0.00 |
| D12 | FX rate from the wrong hour | Kestrel Payouts | 254 | 96.27 | 0.00 |
| D13 | Payout fee cap not applied | Kestrel Payouts | 45 | 1,856.47 | 0.00 |
| D14 | Charge with no matching payment | Brightpay, Northgate Acquiring | 47 | 29.72 | 0.00 |
| D15 | Refund fee not billed | Brightpay | 181 | 0.00 | -36.20 |

## By provider

| Provider | Findings | Overcharge | Undercharge | Recoverable now | Past deadline |
|---|---:|---:|---:|---:|---:|
| Brightpay | 1,232 | 2,822.65 | -36.20 | 309.32 | 2,513.33 |
| Kestrel Payouts | 562 | 3,036.30 | 0.00 | 640.14 | 2,396.16 |
| Northgate Acquiring | 16,436 | 11,392.28 | 0.00 | 3,370.67 | 8,021.61 |

## By month

| Provider | Direction | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 |
|---|---|---:|---:|---:|---:|---:|---:|
| Brightpay | overcharge | 216.83 | 191.56 | 879.74 | 360.38 | 868.29 | 305.85 |
| Brightpay | undercharge | -2.40 | -7.00 | -7.80 | -5.60 | -7.20 | -6.20 |
| Kestrel Payouts | overcharge | 787.30 | 312.56 | 725.49 | 570.81 | 364.77 | 275.37 |
| Northgate Acquiring | overcharge | 27.74 | 2,537.97 | 2,548.33 | 2,909.43 | 3,311.14 | 57.67 |

## Dispute queue

One row per provider invoice. Overcharges after the deadline can no longer be disputed under the contract.

| Provider | Invoice | Invoice date | Deadline | Days left | Status | Overcharges | Overcharge | Recoverable | Undercharge |
|---|---|---|---|---:|---|---:|---:|---:|---:|
| Brightpay | BP-2026-01-001 | 2026-02-03 | 2026-03-05 | -132 | expired | 146 | 213.78 | 0.00 | -2.20 |
| Brightpay | BP-2026-02-001 | 2026-03-03 | 2026-04-02 | -104 | expired | 130 | 192.25 | 0.00 | -7.00 |
| Brightpay | BP-2026-03-001 | 2026-04-03 | 2026-05-03 | -73 | expired | 195 | 871.01 | 0.00 | -7.80 |
| Brightpay | BP-2026-04-001 | 2026-05-03 | 2026-06-02 | -43 | expired | 194 | 355.87 | 0.00 | -5.60 |
| Brightpay | BP-2026-05-001 | 2026-06-03 | 2026-07-03 | -12 | expired | 208 | 880.42 | 0.00 | -7.20 |
| Brightpay | BP-2026-06-001 | 2026-07-03 | 2026-08-02 | 18 | open | 178 | 309.32 | 309.32 | -6.40 |
| Kestrel Payouts | KP202601 | 2026-02-07 | 2026-03-24 | -113 | expired | 115 | 787.30 | 0.00 | 0.00 |
| Kestrel Payouts | KP202602 | 2026-03-07 | 2026-04-21 | -85 | expired | 72 | 312.56 | 0.00 | 0.00 |
| Kestrel Payouts | KP202603 | 2026-04-07 | 2026-05-22 | -54 | expired | 74 | 725.49 | 0.00 | 0.00 |
| Kestrel Payouts | KP202604 | 2026-05-07 | 2026-06-21 | -24 | expired | 109 | 570.81 | 0.00 | 0.00 |
| Kestrel Payouts | KP202605 | 2026-06-07 | 2026-07-22 | 7 | open | 100 | 364.77 | 364.77 | 0.00 |
| Kestrel Payouts | KP202606 | 2026-07-07 | 2026-08-21 | 37 | open | 92 | 275.37 | 275.37 | 0.00 |
| Northgate Acquiring | NG-INV-202601 | 2026-02-05 | 2026-04-06 | -100 | expired | 130 | 26.07 | 0.00 | 0.00 |
| Northgate Acquiring | NG-INV-202602 | 2026-03-05 | 2026-05-04 | -72 | expired | 181 | 2,538.24 | 0.00 | 0.00 |
| Northgate Acquiring | NG-INV-202603 | 2026-04-05 | 2026-06-04 | -41 | expired | 219 | 2,547.48 | 0.00 | 0.00 |
| Northgate Acquiring | NG-INV-202604 | 2026-05-05 | 2026-07-04 | -11 | expired | 15,347 | 2,909.82 | 0.00 | 0.00 |
| Northgate Acquiring | NG-INV-202605 | 2026-06-05 | 2026-08-04 | 20 | open | 286 | 3,311.24 | 3,311.24 | 0.00 |
| Northgate Acquiring | NG-INV-202606 | 2026-07-05 | 2026-09-03 | 50 | open | 273 | 59.43 | 59.43 | 0.00 |
