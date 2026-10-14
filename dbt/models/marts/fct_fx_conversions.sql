-- One row per non-EUR payout that Kestrel converted: mid against applied rate, the realised spread, its cost in EUR
-- and the part above the contractual cap.
with conversions as (
    select *
    from {{ ref('int_charge_comparison') }}
    where component = 'fx_conversion' and event_id is not null and line_count > 0
),

payouts as (
    select * from {{ ref('int_ledger_events') }} where event_type = 'payout'
),

eur_equivalents as (
    select event_id, basis_minor as eur_at_mid_minor
    from {{ ref('int_expected_charges') }}
    where component = 'payout_fee'
),

fx as (
    select pair, hour_start_utc, mid, {{ micros('mid') }} as mid_micros from {{ ref('stg_fx__mid_hourly') }}
)

select
    c.event_id as payout_id,
    c.line_ids[1] as line_id,
    p.client_id,
    p.event_timestamp_utc as executed_at_utc,
    c.month,
    p.currency,
    p.rail,
    p.amount_minor,
    m.mid as mid_rate,
    c.fx_rate_applied as applied_rate,
    c.rate_timestamp_utc,
    c.rate_timestamp_utc = date_trunc('hour', p.event_timestamp_utc) as rate_hour_matches,
    {{ rate_bps('m.mid_micros - ' ~ micros('c.fx_rate_applied'), 'm.mid_micros') }} as spread_bps,
    c.rate_bps as cap_bps,
    e.eur_at_mid_minor,
    c.billed_minor as eur_debited_minor,
    c.billed_minor - e.eur_at_mid_minor as spread_cost_minor,
    c.expected_minor as cap_allowance_minor,
    greatest(0, c.billed_minor - c.expected_minor) as over_cap_cost_minor,
    c.currency as cost_currency,
    c.contract_id,
    c.contract_version,
    c.clause,
    c.comparison_status,
    c.finding_type
from conversions as c
inner join payouts as p on p.event_id = c.event_id
left join eur_equivalents as e on e.event_id = c.event_id
left join fx as m on m.pair = 'EUR' || p.currency and m.hour_start_utc = date_trunc('hour', p.event_timestamp_utc)
