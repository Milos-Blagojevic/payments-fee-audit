with payments as (
    select * from {{ ref('stg_ledger__payments') }}
),

provider_timezones as (
    select distinct counterparty as provider, timezone
    from {{ ref('stg_contracts__contract_versions') }}
    where party = 'provider'
),

events as (
    select
        payment_id as event_id,
        'payment' as event_type,
        client_id,
        provider,
        amount_minor,
        currency,
        created_at_utc as event_timestamp_utc,
        created_at_utc,
        card_scheme,
        card_type,
        card_region,
        status as payment_status,
        cast(null as varchar) as original_payment_id,
        cast(null as varchar) as rail,
        source_file,
        source_row
    from payments

    union all

    -- Refunds and chargebacks go to the provider of the original payment.
    select
        r.refund_id,
        'refund',
        p.client_id,
        p.provider,
        r.amount_minor,
        r.currency,
        r.created_at_utc,
        r.created_at_utc,
        p.card_scheme,
        p.card_type,
        p.card_region,
        null,
        r.payment_id,
        null,
        r.source_file,
        r.source_row
    from {{ ref('stg_ledger__refunds') }} as r
    left join payments as p on p.payment_id = r.payment_id

    union all

    select
        c.chargeback_id,
        'chargeback',
        p.client_id,
        p.provider,
        c.amount_minor,
        c.currency,
        c.created_at_utc,
        c.created_at_utc,
        p.card_scheme,
        p.card_type,
        p.card_region,
        null,
        c.payment_id,
        null,
        c.source_file,
        c.source_row
    from {{ ref('stg_ledger__chargebacks') }} as c
    left join payments as p on p.payment_id = c.payment_id

    union all

    -- A payout is dated by its execution (A13): that is when the provider prices and converts it.
    select
        payout_id,
        'payout',
        client_id,
        provider,
        amount_minor,
        currency,
        executed_at_utc,
        created_at_utc,
        null,
        null,
        null,
        null,
        null,
        rail,
        source_file,
        source_row
    from {{ ref('stg_ledger__payouts') }}
)

select
    e.event_id,
    e.event_type,
    e.client_id,
    e.provider,
    e.amount_minor,
    e.currency,
    e.event_timestamp_utc,
    e.created_at_utc,
    cast(e.event_timestamp_utc as date) as event_date_utc,
    tz.timezone as provider_timezone,
    cast({{ local_from_utc('e.event_timestamp_utc', 'tz.timezone') }} as date) as provider_local_date,
    cast(date_trunc('month', {{ local_from_utc('e.event_timestamp_utc', 'tz.timezone') }}) as date) as provider_month,
    e.card_scheme,
    e.card_type,
    e.card_region,
    {{ card_segment('e.card_type', 'e.card_region') }} as card_segment,
    e.payment_status,
    e.original_payment_id,
    e.rail,
    -- Provider exports have a line for every event they bill: Northgate skips declined and failed attempts,
    -- Brightpay exports every attempt (data contract section 8).
    not (e.provider = 'northgate' and e.event_type = 'payment' and e.payment_status <> 'succeeded')
        as expects_provider_line,
    e.source_file,
    e.source_row
from events as e
left join provider_timezones as tz on tz.provider = e.provider
