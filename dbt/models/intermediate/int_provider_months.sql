-- Every provider × month (contract time zone) with ledger events, its processed volumes, the contract version in
-- force on the month's first day, and whether the ledger covers the whole month yet.
with months as (
    select
        provider,
        provider_month,
        any_value(provider_timezone) as provider_timezone,
        count(*) filter (where event_type = 'payment' and payment_status = 'succeeded') as succeeded_payments,
        coalesce(sum(amount_minor) filter (where event_type = 'payment' and payment_status = 'succeeded'), 0)
            as volume_minor,
        coalesce(
            sum(amount_minor) filter (
                where event_type = 'payment' and payment_status = 'succeeded' and card_segment = 'eea_consumer'
            ),
            0
        ) as eea_consumer_volume_minor,
        coalesce(
            sum(amount_minor) filter (
                where event_type = 'payment' and payment_status = 'succeeded' and card_segment = 'other'
            ),
            0
        ) as other_volume_minor
    from {{ ref('int_ledger_events') }}
    group by provider, provider_month
)

select
    m.provider || ':' || strftime(m.provider_month, '%Y-%m') as provider_month_id,
    m.provider,
    m.provider_month,
    m.provider_timezone,
    {{ utc_from_local('m.provider_month + interval 1 month', 'm.provider_timezone') }} as month_end_utc,
    w.watermark_utc >= {{ utc_from_local('m.provider_month + interval 1 month', 'm.provider_timezone') }}
        as ledger_covers_month,
    m.succeeded_payments,
    m.volume_minor,
    m.eea_consumer_volume_minor,
    m.other_volume_minor,
    v.contract_version_id,
    v.contract_id,
    v.contract_version,
    v.rounding_mode,
    v.other_rounding_mode,
    v.currency
from months as m
cross join {{ ref('int_ledger_watermark') }} as w
left join {{ ref('int_provider_contract_versions') }} as v
    on v.provider = m.provider
    and m.provider_month >= v.effective_from
    and (v.effective_to is null or m.provider_month <= v.effective_to)
