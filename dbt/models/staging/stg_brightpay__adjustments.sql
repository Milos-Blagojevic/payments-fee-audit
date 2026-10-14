with source as (
    select *
    from {{ source('raw', 'brightpay__adjustments') }}
),

-- N01: a re-exported row repeats every field of the original; keep the first occurrence.
deduplicated as (
    select *
    from source
    qualify row_number() over (
        partition by adjustment_id, period, type, description, amount, currency
        order by source_file, source_row
    ) = 1
)

select
    trim(adjustment_id) as adjustment_id,
    {{ month_start('period') }} as period_month,
    lower(trim(type)) as adjustment_type,
    description,
    {{ minor_to_bigint('amount') }} as amount_minor,
    {{ normalize_currency('currency') }} as currency,
    {{ month_from_file_name('source_file') }} as statement_month,
    source_file,
    source_row
from deduplicated
