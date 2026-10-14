select
    trim(chargeback_id) as chargeback_id,
    trim(payment_id) as payment_id,
    {{ utc_from_iso('created_at') }} as created_at_utc,
    {{ minor_to_bigint('amount_minor') }} as amount_minor,
    {{ normalize_currency('currency') }} as currency,
    {{ date_from_file_name('source_file') }} as export_date,
    source_file,
    source_row
from {{ source('raw', 'ledger__chargebacks') }}
