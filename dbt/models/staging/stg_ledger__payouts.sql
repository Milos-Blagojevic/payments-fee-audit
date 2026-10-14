select
    trim(payout_id) as payout_id,
    trim(client_id) as client_id,
    {{ utc_from_iso('created_at') }} as created_at_utc,
    {{ utc_from_iso('executed_at') }} as executed_at_utc,
    {{ minor_to_bigint('amount_minor') }} as amount_minor,
    {{ normalize_currency('currency') }} as currency,
    lower(trim(rail)) as rail,
    lower(trim(provider)) as provider,
    {{ date_from_file_name('source_file') }} as export_date,
    source_file,
    source_row
from {{ source('raw', 'ledger__payouts') }}
