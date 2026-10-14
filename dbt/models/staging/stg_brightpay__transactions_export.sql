with source as (
    select *
    from {{ source('raw', 'brightpay__transactions_export') }}
),

-- N01: a re-exported row repeats every field of the original; keep the first occurrence.
deduplicated as (
    select *
    from source
    qualify row_number() over (
        partition by
            id, type, status, merchant_reference, sub_merchant, created, amount, currency,
            card_network, card_type, card_region, fee, fee_currency
        order by source_file, source_row
    ) = 1
)

select
    trim(id) as line_id,
    lower(trim(type)) as line_type,
    lower(trim(status)) as status,
    nullif(trim(merchant_reference), '') as event_ref,
    nullif(trim(sub_merchant), '') as client_id,
    {{ utc_from_iso('created') }} as event_timestamp_utc,
    -- N02: Brightpay reports minor units.
    {{ minor_to_bigint('amount') }} as event_amount_minor,
    {{ normalize_currency('currency') }} as event_currency,
    {{ normalize_card_scheme('card_network') }} as card_scheme,
    {{ normalize_card_type('card_type') }} as card_type,
    {{ normalize_card_region('card_region') }} as card_region,
    {{ minor_to_bigint('fee') }} as fee_minor,
    {{ normalize_currency('fee_currency') }} as fee_currency,
    {{ month_from_file_name('source_file') }} as statement_month,
    source_file,
    source_row
from deduplicated
