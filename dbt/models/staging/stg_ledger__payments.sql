select
    trim(payment_id) as payment_id,
    trim(client_id) as client_id,
    {{ utc_from_iso('created_at') }} as created_at_utc,
    {{ minor_to_bigint('amount_minor') }} as amount_minor,
    {{ normalize_currency('currency') }} as currency,
    {{ normalize_card_scheme('card_scheme') }} as card_scheme,
    {{ normalize_card_type('card_type') }} as card_type,
    {{ normalize_card_region('card_region') }} as card_region,
    lower(trim(status)) as status,
    lower(trim(provider)) as provider,
    {{ date_from_file_name('source_file') }} as export_date,
    source_file,
    source_row
from {{ source('raw', 'ledger__payments') }}
