{% docs source_file %}
Path of the raw file the row came from, relative to the repository root.
{% enddocs %}

{% docs source_row %}
1-based data row number of the row in its `source_file`.
{% enddocs %}

{% docs statement_month %}
First day of the statement month: the month in the provider file's name (`_<YYYY-MM>.csv`), which is the invoice the line is billed on. Can differ from the event month for lines that arrived late (N04).
{% enddocs %}

{% docs event_month %}
First day of the event's month in the contract's time zone (Northgate Europe/Berlin, others UTC); for monthly lines the month they are for. Lines are assigned to months by this date, not by the file they arrived in (N04).
{% enddocs %}

{% docs provider %}
Provider id: `northgate`, `brightpay` or `kestrel`.
{% enddocs %}

{% docs event_id %}
Fernway ledger event id (`pay_…`, `ref_…`, `cb_…`, `po_…`).
{% enddocs %}

{% docs event_type %}
`payment`, `refund`, `chargeback`, `payout`, or `provider_month` for charges that belong to a provider × month rather than to an event.
{% enddocs %}

{% docs component %}
Fee component (data contract section 4.1): `interchange`, `scheme_fee`, `markup`, `fixed_fee`, `transaction_fee`, `refund_fee`, `markup_credit`, `chargeback_fee`, `monthly_minimum`, `volume_adjustment`, `payout_fee` or `fx_conversion`; or the lower-case name of a Northgate line type the data contract does not list (A40).
{% enddocs %}

{% docs client_id %}
Fernway client id (`CL…`).
{% enddocs %}

{% docs currency %}
ISO 4217 currency code, upper case.
{% enddocs %}

{% docs card_scheme %}
Card scheme, normalised: `visa` or `mastercard`.
{% enddocs %}

{% docs card_type %}
Card type, normalised: `consumer_debit`, `consumer_credit` or `commercial`.
{% enddocs %}

{% docs card_region %}
Card region, normalised: `domestic`, `intra_eea` or `inter_regional`.
{% enddocs %}

{% docs card_segment %}
`eea_consumer` (consumer debit or credit card, domestic or intra-EEA) or `other` (data contract section 2).
{% enddocs %}

{% docs export_date %}
Export date of the ledger file (from its name). The file for export date D holds the events of D − 1 (UTC).
{% enddocs %}

{% docs contract_id %}
Contract id, for example `NG-2025-01`.
{% enddocs %}

{% docs contract_version %}
Version number of the contract.
{% enddocs %}

{% docs clause %}
Clause id of the contract term, as cited in findings (for example `4.2`).
{% enddocs %}

{% docs client_component %}
Client invoice line component (data contract section 4.2): `payment_fees`, `payout_fees_<rail>` (`sepa`, `faster_payments`, `swift`, `elixir`), `fx_markup`, `platform_fee`, `volume_discount` or `promo_discount`.
{% enddocs %}
