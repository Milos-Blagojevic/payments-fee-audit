# Data contract

How the synthetic sources, the contracts and the engines fit together. The generator, the Python reference engine and the dbt engine are three independent implementations of the rules below; none imports another's calculation code. `ASSUMPTIONS.md` gives the reasoning behind each choice (ids in brackets).

## 1. Money, rates and time

- Money is integer minor units (cents) in every table after staging and in all Python code. Every currency in the project has two decimals.
- Rates are integer basis points in contracts and the interchange table. FX rates are decimals with 6 places, quoted as units of the target currency per 1 EUR.
- Rounding is applied exactly as the contract states: `half_up` or `half_even`, at `transaction` level (each fee component of each event is rounded on its own) or `invoice_line` level (client agreements: the exact sum for a client × month × line is rounded once). Python uses `decimal` or exact integer arithmetic; SQL uses integer (`HUGEINT`) arithmetic with explicit rounding macros, never `DOUBLE`, for money.
- Timestamps in staged data are UTC. Months for tiers and minimums use the contract's `timezone` (Northgate `Europe/Berlin`, others `UTC`) [A02]. The contract version for an event is the one whose `[effective_from, next effective_from)` contains the event timestamp in the contract's timezone [A03].
- All card payments are in EUR [A11]. Payouts are in EUR, GBP, USD, CHF or PLN; every provider fee is billed in EUR.

## 2. Card segments

- `card_scheme`: `visa`, `mastercard`. `card_type`: `consumer_debit`, `consumer_credit`, `commercial`. `card_region`: `domestic`, `intra_eea`, `inter_regional`.
- Segment `eea_consumer`: consumer debit or credit with region `domestic` or `intra_eea`. Segment `other`: everything else.

## 3. Ledger (internal source of truth)

CSV, one file per table per export day: `data/raw/ledger/<table>/ledger_<table>_<export date>.csv`. The file for export date D holds the events of D − 1 (UTC), so the last day of the period is missing at the period end (N07). Ledger files are clean: integer minor units, ISO-8601 UTC timestamps with `Z`.

| Table | Columns |
|---|---|
| `ledger__payments` | `payment_id`, `client_id`, `created_at`, `amount_minor`, `currency`, `card_scheme`, `card_type`, `card_region`, `status` (`succeeded`, `declined`, `failed`), `provider` (`northgate`, `brightpay`) |
| `ledger__refunds` | `refund_id`, `payment_id`, `created_at`, `amount_minor`, `currency` (always a full refund of the payment) |
| `ledger__chargebacks` | `chargeback_id`, `payment_id`, `created_at`, `amount_minor`, `currency` |
| `ledger__payouts` | `payout_id`, `client_id`, `created_at`, `executed_at`, `amount_minor` (in the payout currency), `currency`, `rail` (`sepa`, `faster_payments`, `swift`, `elixir`), `provider` (`kestrel`) |
| `fernway__clients` | `client_id`, `client_name`, `country`, `card_provider` (initial), `card_provider_switch_date`, `card_provider_after_switch` |

Every source file is loaded as-is into schema `raw` of `warehouse/fees.duckdb`, one table per source entity across all its files: every source column as `VARCHAR` with the source's own name, plus `source_file` (path relative to the repository root) and `source_row` (1-based data row number in that file). Parsing happens only in dbt staging and in the Python reference engine.

Refunds and chargebacks go to the provider of the original payment. Rails: EUR → `sepa`, GBP → `faster_payments`, USD and CHF → `swift`, PLN → `swift` before 2026-04-01 and mostly `elixir` after.

`fx__mid_hourly`: `pair` (`EURGBP`, `EURUSD`, `EURCHF`, `EURPLN`), `hour_start_utc`, `mid` (6 decimals).

Provider exports, invoices and client invoices are documented in section 8 (written by the generator; each source keeps its own column names and quirks).

## 4. Contracts

One YAML per contract version in `contracts/providers/` and `contracts/clients/`, validated by the JSON Schema in `feeaudit/`. Each version is complete (it repeats unchanged terms). Every term has a `clause` id that findings cite. Interchange and scheme fee reference: `dbt/seeds/interchange_table_v1.csv` (illustrative, keyed by scheme × card type × region) [A07].

### 4.1 Provider term kinds and expected charges

| Kind | Component(s) | Expected charge |
|---|---|---|
| `pass_through` | `interchange`, `scheme_fee` | Per successful payment: `round(amount × interchange_bps / 10000)`; `round(amount × scheme_fee_bps / 10000) + scheme_fee_fixed_minor` |
| `markup_bps_tiered` (retroactive) | `markup` | Per successful payment: `round(amount × bps / 10000)` where bps is the tier that the month's total processed volume (successful payments at that provider, contract-timezone month) falls in. `up_to_minor` is an exclusive upper bound: volume `< up_to_minor` is in the tier |
| `per_transaction_fixed` | `fixed_fee` | Per successful payment |
| `blended_rate` | `transaction_fee` | Per payment attempt: `round(amount × bps / 10000) + fixed_minor` by segment for `succeeded`; `0` for `declined` and `failed` (`failed_attempts: no_fee`) |
| `volume_discount` (marginal, monthly adjustment) | `volume_adjustment` | Per provider × month: `−round((V − threshold) × (first tier bps − second tier bps) / 10000)` when the month's segment volume V exceeds the first tier's `up_to_minor`, else `0`. Transaction fees are billed at the first tier rate |
| `refund` | `refund_fee`, `markup_credit` | Per refund: `fee_minor`; if `credit_original_markup`, a `markup_credit` of minus the **expected** markup of the original payment (its own month's tier, its own contract version) |
| `chargeback_fee` | `chargeback_fee` | Per chargeback |
| `monthly_minimum` | `monthly_minimum` | Per provider × month: `max(0, amount_minor − sum of expected markup on the month's payments)` (credits not netted) |
| `payout_fee` | `payout_fee` | Per payout by rail: `fixed_minor`; or `clamp(round(E × bps / 10000), min_minor, cap_minor)` where E = `round(amount_minor / mid)` is the EUR equivalent at the execution-hour mid |
| `fx_spread_cap` | `fx_conversion` | Per non-EUR payout: the largest EUR debit the cap allows, `round(amount_minor / (mid × (1 − cap_bps / 10000)))`, mid at the hour containing `executed_at`. A **cap**, not an exact price: only a billed debit above it is a finding |

`round` is the contract's rounding mode. The expected-charges grain is ledger event × component, plus provider × month rows for `monthly_minimum` and `volume_adjustment` (emitted for every provider month, including zeros). Events in the ledger only.

### 4.2 Client term kinds (Fernway's pricing agreements)

`payment_fee_by_segment` (`bps`, `fixed_minor` per segment, on succeeded payments), `payout_fee_by_rail` (`fixed_minor` per rail), `fx_markup` (`bps` on the EUR equivalent at mid of non-EUR payouts), `platform_fee` (monthly `amount_minor`), `volume_discount_tiered` (retroactive, `discount_pct` of payment fees by the client's monthly processed volume), `promo_discount` (`discount_pct` of payment fees, `valid_until` date inclusive). Rounding `half_up` at `invoice_line` level. Invoice line components: `payment_fees`, `payout_fees_<rail>`, `fx_markup`, `platform_fee`, `volume_discount`, `promo_discount`.

## 5. Finding types

Each planted type has exactly one finding type. Evaluation matches findings to truth by the unit key.

| Truth id | `finding_type` | Unit key | Direction |
|---|---|---|---|
| D01 | `stale_rate` | provider line id (markup line) | over |
| D02 | `retroactive_tier_not_applied` | provider × month | over |
| D03 | `pass_through_above_reference` | provider line id | over |
| D04 | `refund_credit_missing` | refund event id | over |
| D05 | `minimum_not_due` | provider × month | over |
| D06 | `duplicate_charge` | the duplicate line id | over |
| D07 | `wrong_card_segment` | provider line id | over |
| D08 | `fee_on_failed_attempt` | provider line id | over |
| D09 | `chargeback_fee_mismatch` | provider line id | over |
| D10 | `volume_discount_not_applied` | provider × month | over |
| D11 | `fx_spread_above_cap` | provider line id | over |
| D12 | `fx_rate_wrong_hour` | provider line id | over |
| D13 | `payout_fee_cap_not_applied` | provider line id | over |
| D14 | `unknown_charge` | provider line id | over |
| D15 | `refund_fee_missing` | refund event id | under |
| L01 | `rail_not_billed` | client × month × component | under |
| L02 | `promo_after_end_date` | client × month × component | under |
| L03 | `fx_markup_not_billed` | client × month × component | under |
| L04 | `volume_discount_too_high` | client × month × component | under |
| — | `rounding` | provider line id | either; never an overcharge |
| — | `fee_mismatch` | provider line id | any difference no rule explains (zero expected for the default seed) |

Rule semantics the generator plants and the engine detects:

- D01: markup at the previous contract version's rate for the same tier, on Northgate payments in the first 12 days after the amendment (Berlin dates).
- D02: in a month whose volume crosses the first threshold, payments are billed at the first tier rate until the running volume (timestamp order) reaches the threshold, then at the month's tier rate. Not planted in the month of D01.
- D12: the Kestrel statement shows a rate timestamp outside the execution hour. Money: billed debit − `round(amount_minor / (applied_rate × mid_exec / mid_rate_hour))`, but not below the D11 allowance. A D12 line is never also a D11.
- `rounding`: |difference| is 1 minor unit and the billed amount equals the expected amount under the other rounding mode.
- At most one discrepancy per provider line; no discrepancy on events whose provider lines fall in the ledger lag window.

## 6. Noise (never a finding)

N01 exact duplicate rows (same line id) in a re-exported file; N02 Brightpay amounts in minor units, others in major units, one Northgate file with comma decimals and `;` delimiter; N03 Northgate timestamps in Europe/Berlin local time without offset; N04 lines for the last days of a month in the next month's file; N05 lower-case or padded currency codes and inconsistent card labels; N06 about 2% of lines without a provider reference (fallback: amount, currency, ±48 h, client, one-to-one, among ledger events not matched by reference); N07 the ledger lag at the period end (provider lines after the ledger watermark are `unmatched_pending`); N08 Brightpay rounding some ties half-up instead of half-even (a `rounding` finding, never an overcharge).

## 7. Truth (schema `truth`, read only by `feeaudit/evaluation`)

- `discrepancies`: `discrepancy_id`, `truth_id` (D01..D15), `provider`, `month`, `event_id`, `line_ids` (list), `correct_minor`, `billed_minor`, `difference_minor`, `currency`.
- `client_leakage`: `truth_id` (L01..L04), `client_id`, `month`, `component`, `correct_minor`, `billed_minor`, `difference_minor`.
- `noise_events`: `truth_id` (N01..N08), `source_file`, `source_row`, `line_id`, `event_id`.
- `parameters`: every generator parameter and the seed.

## 8. Provider exports and invoices

Written by the generator; this section is completed in phase 2 with each file's path pattern, columns, units and quirks.
