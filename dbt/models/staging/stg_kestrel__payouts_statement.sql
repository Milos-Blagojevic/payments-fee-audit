with source as (
    select *
    from {{ source('raw', 'kestrel__payouts_statement') }}
),

-- N01: a re-exported row repeats every field of the original; keep the first occurrence.
deduplicated as (
    select *
    from source
    qualify row_number() over (
        partition by
            statement_line_id, client_payout_ref, client_id, payout_currency, payout_amount, rail, fee_eur,
            fx_rate_applied, rate_timestamp, eur_debited, executed_at
        order by source_file, source_row
    ) = 1
)

select
    trim(statement_line_id) as line_id,
    nullif(trim(client_payout_ref), '') as event_ref,
    nullif(trim(client_id), '') as client_id,
    {{ normalize_currency('payout_currency') }} as payout_currency,
    {{ major_to_minor('payout_amount') }} as payout_amount_minor,
    lower(trim(rail)) as rail,
    {{ major_to_minor('fee_eur') }} as fee_minor,
    cast(nullif(trim(fx_rate_applied), '') as decimal(18, 6)) as fx_rate_applied,
    {{ utc_from_iso("nullif(trim(rate_timestamp), '')") }} as rate_timestamp_utc,
    {{ major_to_minor('eur_debited') }} as eur_debited_minor,
    {{ utc_from_iso('executed_at') }} as executed_at_utc,
    {{ month_from_file_name('source_file') }} as statement_month,
    source_file,
    source_row
from deduplicated
