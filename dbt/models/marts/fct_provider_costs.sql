-- Billed and expected provider fees per provider × UTC month × fee component × card segment, with the processed
-- volume they relate to. FX conversion debits are not fees (the spread cost is in fct_fx_conversions).
with charges as (
    select
        provider,
        coalesce(cast(date_trunc('month', event_timestamp_utc) as date), month) as month,
        component,
        case
            when card_segment is not null then card_segment
            when event_type in ('payout', 'provider_month') then 'not_applicable'
            else 'unknown'
        end as card_segment,
        comparison_status,
        expected_minor,
        billed_minor,
        line_count
    from {{ ref('int_charge_comparison') }}
    where component <> 'fx_conversion'
),

costs as (
    select
        provider,
        month,
        component,
        card_segment,
        sum(line_count) as lines,
        sum(billed_minor) as billed_minor,
        coalesce(sum(billed_minor) filter (where comparison_status = 'pending'), 0) as pending_billed_minor,
        coalesce(sum(expected_minor) filter (where comparison_status = 'compared'), 0) as expected_minor,
        coalesce(sum(billed_minor - expected_minor) filter (where comparison_status = 'compared'), 0)
            as difference_minor
    from charges
    group by all
),

-- M01 by provider × UTC month × card segment; rows without a card segment relate to the provider's whole volume.
volumes as (
    select provider, month, card_segment, sum(volume_minor) over (partition by provider, month) as provider_volume_minor,
        volume_minor
    from (
        select
            provider,
            cast(date_trunc('month', event_timestamp_utc) as date) as month,
            card_segment,
            sum(amount_minor) as volume_minor
        from {{ ref('int_ledger_events') }}
        where event_type = 'payment' and payment_status = 'succeeded'
        group by all
    )
),

provider_volumes as (
    select distinct provider, month, provider_volume_minor from volumes
)

select
    c.provider || ':' || strftime(c.month, '%Y-%m') || ':' || c.component || ':' || c.card_segment as provider_cost_id,
    c.provider,
    c.month,
    c.component,
    c.card_segment,
    c.lines,
    c.billed_minor,
    c.pending_billed_minor,
    c.expected_minor,
    c.difference_minor,
    case when c.card_segment in ('eea_consumer', 'other') then v.volume_minor else pv.provider_volume_minor end
        as volume_minor,
    {{ rate_bps(
        'c.billed_minor',
        "case when c.card_segment in ('eea_consumer', 'other') then v.volume_minor else pv.provider_volume_minor end"
    ) }} as effective_rate_bps
from costs as c
left join volumes as v on v.provider = c.provider and v.month = c.month and v.card_segment = c.card_segment
left join provider_volumes as pv on pv.provider = c.provider and pv.month = c.month
