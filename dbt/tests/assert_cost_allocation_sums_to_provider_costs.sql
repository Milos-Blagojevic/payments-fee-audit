-- The client cost allocation adds back to the provider costs: every invoiced provider line component is allocated
-- exactly (no line lost, none split wrongly), and per month the client margin's provider fees (with the pending
-- part) and FX spread cost equal the allocated fees and the payouts' spread cost.
with lines as (
    select line_component_id, amount_minor from {{ ref('int_provider_lines') }} where is_invoiced
),

allocated as (
    select line_component_id, sum(allocated_minor) as allocated_minor
    from {{ ref('int_provider_cost_allocation') }}
    group by line_component_id
),

allocated_months as (
    select month, sum(allocated_minor) as fees_minor
    from {{ ref('int_provider_cost_allocation') }}
    group by month
),

spread_months as (
    select cast(date_trunc('month', executed_at_utc) as date) as month, sum(spread_cost_minor) as spread_minor
    from {{ ref('fct_fx_conversions') }}
    group by all
),

margin_months as (
    select
        month,
        sum(provider_fees_minor + pending_provider_fees_minor) as fees_minor,
        sum(fx_spread_cost_minor) as spread_minor
    from {{ ref('fct_client_margin') }}
    group by month
)

select 'line ' || coalesce(l.line_component_id, a.line_component_id) as unit, l.amount_minor as expected_minor,
    a.allocated_minor as actual_minor
from lines as l
full outer join allocated as a on a.line_component_id = l.line_component_id
where l.amount_minor is distinct from a.allocated_minor

union all

select 'fees ' || strftime(coalesce(a.month, m.month), '%Y-%m'), a.fees_minor, m.fees_minor
from allocated_months as a
full outer join margin_months as m on m.month = a.month
where coalesce(a.fees_minor, 0) <> coalesce(m.fees_minor, 0)

union all

select 'fx spread ' || strftime(coalesce(s.month, m.month), '%Y-%m'), s.spread_minor, m.spread_minor
from spread_months as s
full outer join margin_months as m on m.month = s.month
where coalesce(s.spread_minor, 0) <> coalesce(m.spread_minor, 0)
