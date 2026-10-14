-- Invoiced provider fees allocated to clients (A09, A32): one row per provider line component × client. A charge
-- that belongs to a ledger event goes to that event's client and UTC month (payouts by execution); a line with no
-- ledger event (an unknown charge, a line after the ledger watermark) to the client the provider reported and the
-- month of the event time it reported. A monthly charge with no event (monthly minimum, volume adjustment) is split
-- across the provider's clients by their share of the volume the term is computed on, in whole minor units with
-- largest remainders, so the parts add up to the line exactly.
with lines as (
    select
        l.line_component_id,
        l.line_id,
        l.provider,
        l.component,
        l.event_type,
        l.amount_minor,
        l.currency,
        l.client_id as reported_client_id,
        l.event_timestamp_utc,
        l.event_month,
        r.event_id,
        r.status = 'unmatched_pending' as is_pending
    from {{ ref('int_provider_lines') }} as l
    left join {{ ref('int_reconciliation') }} as r on r.line_id = l.line_id
    where l.is_invoiced
),

event_allocations as (
    select
        l.line_component_id,
        l.line_id,
        l.provider,
        l.component,
        coalesce(e.client_id, l.reported_client_id) as client_id,
        cast(date_trunc('month', coalesce(e.event_timestamp_utc, l.event_timestamp_utc)) as date) as month,
        case when e.event_id is not null then 'event' else 'reported_client' end as allocation_method,
        l.event_id,
        l.is_pending,
        l.amount_minor as line_amount_minor,
        cast(null as bigint) as basis_volume_minor,
        cast(null as bigint) as total_basis_volume_minor,
        l.amount_minor as allocated_minor,
        l.currency
    from lines as l
    left join {{ ref('int_ledger_events') }} as e on e.event_id = l.event_id
    where l.event_type <> 'provider_month'
),

-- Volumes per provider × month in the contract's time zone, the basis of minimums and volume adjustments.
client_volumes as (
    select
        provider,
        provider_month,
        client_id,
        sum(amount_minor) as volume_minor,
        coalesce(sum(amount_minor) filter (where card_segment = 'eea_consumer'), 0) as eea_consumer_volume_minor
    from {{ ref('int_ledger_events') }}
    where event_type = 'payment' and payment_status = 'succeeded'
    group by all
),

-- The monthly minimum tops up the markup on all processed volume; the volume adjustment is a discount on EEA
-- consumer volume (data contract section 4.1).
monthly_shares as (
    select
        l.*,
        v.client_id,
        case l.component
            when 'volume_adjustment' then v.eea_consumer_volume_minor
            else v.volume_minor
        end as basis_volume_minor
    from lines as l
    inner join client_volumes as v on v.provider = l.provider and v.provider_month = l.event_month
    where l.event_type = 'provider_month'
),

monthly_parts as (
    select
        *,
        sum(basis_volume_minor) over (partition by line_component_id) as total_basis_volume_minor,
        abs(cast(amount_minor as hugeint)) * basis_volume_minor
            // sum(basis_volume_minor) over (partition by line_component_id) as floor_minor,
        abs(cast(amount_minor as hugeint)) * basis_volume_minor
            % sum(basis_volume_minor) over (partition by line_component_id) as remainder
    from monthly_shares
    where basis_volume_minor > 0
),

monthly_ranked as (
    select
        *,
        row_number() over (partition by line_component_id order by remainder desc, client_id) as remainder_rank,
        abs(amount_minor) - sum(floor_minor) over (partition by line_component_id) as leftover_minor
    from monthly_parts
),

monthly_allocations as (
    select
        line_component_id,
        line_id,
        provider,
        component,
        client_id,
        event_month as month,
        'volume_share' as allocation_method,
        event_id,
        is_pending,
        amount_minor as line_amount_minor,
        basis_volume_minor,
        cast(total_basis_volume_minor as bigint) as total_basis_volume_minor,
        cast(sign(amount_minor) * (floor_minor + case when remainder_rank <= leftover_minor then 1 else 0 end) as bigint)
            as allocated_minor,
        currency
    from monthly_ranked
)

select
    line_component_id || ':' || client_id as allocation_id,
    *
from (
    select * from event_allocations
    union all by name
    select * from monthly_allocations
)
