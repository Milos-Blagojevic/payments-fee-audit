with provider_timezones as (
    select distinct counterparty as provider, timezone
    from {{ ref('stg_contracts__contract_versions') }}
    where party = 'provider'
),

northgate as (
    select
        line_id,
        'northgate' as provider,
        event_ref,
        case
            when line_type in ('INTERCHANGE', 'SCHEME_FEE', 'MARKUP', 'FIXED_FEE') then 'payment'
            when line_type in ('REFUND_FEE', 'MARKUP_CREDIT') then 'refund'
            when line_type = 'CHARGEBACK_FEE' then 'chargeback'
            when line_type = 'MONTHLY_MINIMUM' then 'provider_month'
        end as event_type,
        case line_type
            when 'INTERCHANGE' then 'interchange'
            when 'SCHEME_FEE' then 'scheme_fee'
            when 'MARKUP' then 'markup'
            when 'FIXED_FEE' then 'fixed_fee'
            when 'REFUND_FEE' then 'refund_fee'
            when 'MARKUP_CREDIT' then 'markup_credit'
            when 'CHARGEBACK_FEE' then 'chargeback_fee'
            when 'MONTHLY_MINIMUM' then 'monthly_minimum'
        end as component,
        fee_minor as amount_minor,
        fee_currency as currency,
        true as is_invoiced,
        client_id,
        event_amount_minor,
        event_currency,
        event_timestamp_utc,
        period_month,
        statement_month,
        card_scheme,
        card_type,
        card_region,
        cast(null as varchar) as payment_status,
        cast(null as varchar) as rail,
        cast(null as varchar) as payout_currency,
        cast(null as decimal(18, 6)) as fx_rate_applied,
        cast(null as timestamp) as rate_timestamp_utc,
        source_file,
        source_row
    from {{ ref('stg_northgate__settlement_lines') }}
),

brightpay as (
    select
        line_id,
        'brightpay' as provider,
        event_ref,
        line_type as event_type,
        case line_type
            when 'payment' then 'transaction_fee'
            when 'refund' then 'refund_fee'
            when 'chargeback' then 'chargeback_fee'
        end as component,
        fee_minor as amount_minor,
        fee_currency as currency,
        true as is_invoiced,
        client_id,
        event_amount_minor,
        event_currency,
        event_timestamp_utc,
        cast(null as date) as period_month,
        statement_month,
        card_scheme,
        card_type,
        card_region,
        case status when 'captured' then 'succeeded' when 'completed' then null else status end as payment_status,
        null as rail,
        null as payout_currency,
        null as fx_rate_applied,
        null as rate_timestamp_utc,
        source_file,
        source_row
    from {{ ref('stg_brightpay__transactions_export') }}

    union all

    select
        adjustment_id,
        'brightpay',
        null,
        'provider_month',
        case adjustment_type when 'volume_discount' then 'volume_adjustment' end,
        amount_minor,
        currency,
        true,
        null,
        null,
        null,
        null,
        period_month,
        statement_month,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        source_file,
        source_row
    from {{ ref('stg_brightpay__adjustments') }}
),

-- A Kestrel statement line carries two charges: the payout fee (invoiced) and, for a non-EUR payout, the EUR
-- debited for the conversion (settled against the account balance, not invoiced).
kestrel as (
    select
        line_id,
        'kestrel' as provider,
        event_ref,
        'payout' as event_type,
        c.component,
        case c.component when 'payout_fee' then fee_minor else eur_debited_minor end as amount_minor,
        'EUR' as currency,
        c.component = 'payout_fee' as is_invoiced,
        client_id,
        payout_amount_minor as event_amount_minor,
        payout_currency as event_currency,
        executed_at_utc as event_timestamp_utc,
        cast(null as date) as period_month,
        statement_month,
        null as card_scheme,
        null as card_type,
        null as card_region,
        null as payment_status,
        rail,
        payout_currency,
        fx_rate_applied,
        rate_timestamp_utc,
        source_file,
        source_row
    from {{ ref('stg_kestrel__payouts_statement') }}
    cross join (values ('payout_fee'), ('fx_conversion')) as c (component)
    where c.component = 'payout_fee' or payout_currency <> 'EUR'
),

lines as (
    select * from northgate
    union all by name
    select * from brightpay
    union all by name
    select * from kestrel
)

select
    l.line_id || ':' || l.component as line_component_id,
    l.line_id,
    l.provider,
    l.event_ref,
    l.event_type,
    l.component,
    -- The unit the fallback match pairs one-to-one: one line per event × component, one Kestrel line per payout.
    case when l.provider = 'kestrel' then 'payout' else l.component end as match_slot,
    l.amount_minor,
    l.currency,
    l.is_invoiced,
    l.client_id,
    l.event_amount_minor,
    l.event_currency,
    l.event_timestamp_utc,
    -- N04: months by event date in the contract's time zone, not by the file the line arrived in.
    coalesce(
        l.period_month,
        cast(date_trunc('month', {{ local_from_utc('l.event_timestamp_utc', 'tz.timezone') }}) as date)
    ) as event_month,
    l.statement_month,
    l.card_scheme,
    l.card_type,
    l.card_region,
    {{ card_segment('l.card_type', 'l.card_region') }} as billed_card_segment,
    l.payment_status,
    l.rail,
    l.payout_currency,
    l.fx_rate_applied,
    l.rate_timestamp_utc,
    l.source_file,
    l.source_row
from lines as l
left join provider_timezones as tz on tz.provider = l.provider
