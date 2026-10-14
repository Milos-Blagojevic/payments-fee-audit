with source as (
    select *
    from {{ source('raw', 'northgate__settlement_lines') }}
),

-- N01: a re-exported row repeats every field of the original; keep the first occurrence.
deduplicated as (
    select *
    from source
    qualify row_number() over (
        partition by
            line_ref, txn_ref, merchant_ref, txn_time, period, line_type, txn_amount, txn_currency,
            card_brand, card_product, card_region, fee_amount, fee_currency
        order by source_file, source_row
    ) = 1
)

select
    trim(line_ref) as line_id,
    nullif(trim(txn_ref), '') as event_ref,
    nullif(trim(merchant_ref), '') as client_id,
    -- N03: Europe/Berlin wall-clock time without offset.
    {{ utc_from_local('txn_time', "'Europe/Berlin'") }} as event_timestamp_utc,
    {{ month_start('period') }} as period_month,
    upper(trim(line_type)) as line_type,
    -- N02: major units, decimal commas in one file.
    {{ major_to_minor('txn_amount') }} as event_amount_minor,
    {{ normalize_currency('txn_currency') }} as event_currency,
    {{ normalize_card_scheme('card_brand') }} as card_scheme,
    {{ normalize_card_type('card_product') }} as card_type,
    {{ normalize_card_region('card_region') }} as card_region,
    {{ major_to_minor('fee_amount') }} as fee_minor,
    {{ normalize_currency('fee_currency') }} as fee_currency,
    {{ month_from_file_name('source_file') }} as statement_month,
    source_file,
    source_row
from deduplicated
