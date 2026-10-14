-- Client × UTC month: what Fernway billed and should have billed (M09 revenue leakage), the provider costs of the
-- client's events (A09, A32) and the margin (M10). Revenue and costs cover the same events: the ledger export.
-- Provider lines after the ledger watermark are billed to the client in the next cycle (A12), so their fees are
-- shown as pending and kept out of this month's margin.
with billing as (
    select
        client_id,
        month,
        sum(billed_minor) as billed_minor,
        sum(expected_minor) as expected_minor
    from {{ ref('int_client_billing_comparison') }}
    group by all
),

provider_fees as (
    select
        client_id,
        month,
        coalesce(sum(allocated_minor) filter (where not is_pending and allocation_method <> 'volume_share'), 0)
            as event_fees_minor,
        coalesce(sum(allocated_minor) filter (where not is_pending and allocation_method = 'volume_share'), 0)
            as volume_share_fees_minor,
        coalesce(sum(allocated_minor) filter (where is_pending), 0) as pending_fees_minor
    from {{ ref('int_provider_cost_allocation') }}
    group by all
),

-- M08 per payout: the provider's FX spread, which the client FX markup is priced to cover.
fx_spread as (
    select
        client_id,
        cast(date_trunc('month', executed_at_utc) as date) as month,
        sum(spread_cost_minor) as fx_spread_cost_minor
    from {{ ref('fct_fx_conversions') }}
    group by all
),

volumes as (
    select
        client_id,
        cast(date_trunc('month', event_timestamp_utc) as date) as month,
        sum(amount_minor) as volume_minor
    from {{ ref('int_ledger_events') }}
    where event_type = 'payment' and payment_status = 'succeeded'
    group by all
),

client_months as (
    select client_id, month from billing
    union
    select client_id, month from provider_fees
    union
    select client_id, month from fx_spread
),

margin as (
    select
        m.client_id,
        m.month,
        coalesce(v.volume_minor, 0) as volume_minor,
        coalesce(b.billed_minor, 0) as billed_minor,
        coalesce(b.expected_minor, 0) as expected_minor,
        coalesce(p.event_fees_minor, 0) as event_provider_fees_minor,
        coalesce(p.volume_share_fees_minor, 0) as volume_share_provider_fees_minor,
        coalesce(p.event_fees_minor, 0) + coalesce(p.volume_share_fees_minor, 0) as provider_fees_minor,
        coalesce(f.fx_spread_cost_minor, 0) as fx_spread_cost_minor,
        coalesce(p.pending_fees_minor, 0) as pending_provider_fees_minor
    from client_months as m
    left join billing as b on b.client_id = m.client_id and b.month = m.month
    left join provider_fees as p on p.client_id = m.client_id and p.month = m.month
    left join fx_spread as f on f.client_id = m.client_id and f.month = m.month
    left join volumes as v on v.client_id = m.client_id and v.month = m.month
)

select
    client_id || ':' || strftime(month, '%Y-%m') as client_margin_id,
    client_id,
    month,
    volume_minor,
    billed_minor,
    expected_minor,
    expected_minor - billed_minor as revenue_leakage_minor,
    event_provider_fees_minor,
    volume_share_provider_fees_minor,
    provider_fees_minor,
    fx_spread_cost_minor,
    provider_fees_minor + fx_spread_cost_minor as provider_cost_minor,
    billed_minor - provider_fees_minor - fx_spread_cost_minor as margin_minor,
    {{ rate_bps('billed_minor - provider_fees_minor - fx_spread_cost_minor', 'volume_minor') }} as margin_bps,
    pending_provider_fees_minor,
    'EUR' as currency
from margin
