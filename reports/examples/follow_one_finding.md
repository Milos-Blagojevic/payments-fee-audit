# Follow one finding

One finding of type `wrong_card_segment` (Card priced in the wrong segment), followed from the provider's raw file to the finding. It is the first finding of that type by month and event id. Every value below is read from `warehouse/fees.duckdb` when the report is built (`python -m feeaudit.reports`). Money is in minor units (cents) in the tables and in EUR in the text.

## 1. The raw file row

Line `bp_000000111` is data row 111 (file line 112, after the header) of `data/raw/brightpay/transactions_export/brightpay_transactions_2026-01.csv`, loaded verbatim as text into `raw.brightpay__transactions_export`:

| Column | Value |
|---|---|
| `id` | `bp_000000111` |
| `type` | `payment` |
| `status` | `captured` |
| `merchant_reference` | `pay_0000267` |
| `sub_merchant` | `CL014` |
| `created` | `2026-01-01T09:48:37Z` |
| `amount` | `8500` |
| `currency` | `EUR` |
| `card_network` | `visa` |
| `card_type` | `consumer_debit` |
| `card_region` | `intra_eea` |
| `fee` | `271` |
| `fee_currency` | `EUR` |

The ledger event it refers to is data row 267 of `data/raw/ledger/payments/ledger_payments_2026-01-02.csv` (`raw.ledger__payments`):

| Column | Value |
|---|---|
| `payment_id` | `pay_0000267` |
| `client_id` | `CL014` |
| `created_at` | `2026-01-01T09:48:37Z` |
| `amount_minor` | `8500` |
| `currency` | `EUR` |
| `card_scheme` | `visa` |
| `card_type` | `consumer_debit` |
| `card_region` | `intra_eea` |
| `status` | `succeeded` |
| `provider` | `brightpay` |

## 2. The staging rows

`stg_brightpay__transactions_export` types and cleans the provider row (labels, units, UTC time):

| Column | Value |
|---|---|
| `line_id` | `bp_000000111` |
| `line_type` | `payment` |
| `status` | `captured` |
| `event_ref` | `pay_0000267` |
| `client_id` | `CL014` |
| `event_timestamp_utc` | `2026-01-01 09:48:37` |
| `event_amount_minor` | `8500` |
| `event_currency` | `EUR` |
| `card_scheme` | `visa` |
| `card_type` | `consumer_debit` |
| `card_region` | `intra_eea` |
| `fee_minor` | `271` |
| `fee_currency` | `EUR` |
| `statement_month` | `2026-01-01` |

`stg_ledger__payments` does the same for the ledger event:

| Column | Value |
|---|---|
| `payment_id` | `pay_0000267` |
| `client_id` | `CL014` |
| `created_at_utc` | `2026-01-01 09:48:37` |
| `amount_minor` | `8500` |
| `currency` | `EUR` |
| `card_scheme` | `visa` |
| `card_type` | `consumer_debit` |
| `card_region` | `intra_eea` |
| `status` | `succeeded` |
| `provider` | `brightpay` |
| `export_date` | `2026-01-02` |

## 3. The reconciliation match

`int_reconciliation` matches the line to ledger event `pay_0000267` by `reference` with status `matched`. `int_provider_lines` splits the line into fee components; the `transaction_fee` component is billed at 271 cents and the card is in segment `eea_consumer` (consumer_debit, intra_eea).

| Column | Value |
|---|---|
| `line_id` | `bp_000000111` |
| `event_id` | `pay_0000267` |
| `event_type` | `payment` |
| `match_slot` | `transaction_fee` |
| `match_method` | `reference` |
| `status` | `matched` |
| `statement_month` | `2026-01-01` |

## 4. The expected charge

The contract in force on 2026-01-01 is BP-2025-07 version 1. Clause 3.1, *All-in fee per payment by card segment; no fee on declined or failed attempts*: EEA consumer cards 1.40% + 0.25, other cards 2.90% + 0.25 EUR per successful payment; no fee on declined or failed attempts.

`int_expected_charges` applies it to the payment: **85.00 × 1.40% + 0.25 = 1.44 EUR (BP-2025-07 v1 §3.1; segment eea_consumer)**, so 144 cents are due.

| Column | Value |
|---|---|
| `expected_charge_id` | `payment:pay_0000267:transaction_fee` |
| `basis_minor` | `8500` |
| `card_segment` | `eea_consumer` |
| `rate_bps` | `140` |
| `expected_minor` | `144` |
| `formula` | `85.00 × 1.40% + 0.25 = 1.44 EUR (BP-2025-07 v1 §3.1; segment eea_consumer)` |

## 5. The finding

`int_charge_comparison` puts the billed and the expected amount side by side: billed 271, expected 144, difference 127 cents, classified `wrong_card_segment`.

The amount billed, 2.71, is exactly the fee at the `other` segment rate: 85.00 × 2.90% + 0.25, rounded half even, = 2.71. The provider priced the card (segment `eea_consumer`) at the `other` rate.

`fct_findings` records it as an overcharge of EUR 1.27 on invoice BP-2026-01-001 (dated 2026-02-03); the dispute deadline is 2026-03-05, 132 days before the reference date 2026-07-15 (A22).

| Column | Value |
|---|---|
| `finding_id` | `b703cc4be453a6d1f4280d0e6fe72fe3` |
| `finding_type` | `wrong_card_segment` |
| `counterparty` | `brightpay` |
| `month` | `2026-01-01` |
| `event_id` | `pay_0000267` |
| `line_ids` | `['bp_000000111']` |
| `component` | `transaction_fee` |
| `clause` | `3.1` |
| `expected_minor` | `144` |
| `billed_minor` | `271` |
| `difference_minor` | `127` |
| `direction` | `over` |
| `invoice_id` | `BP-2026-01-001` |
| `dispute_deadline` | `2026-03-05` |
| `evidence` | `data/raw/brightpay/transactions_export/brightpay_transactions_2026-01.csv:111; data/raw/ledger/payments/ledger_payments_2026-01-02.csv:267; contracts/providers/brightpay-v1.yml §3.1` |
