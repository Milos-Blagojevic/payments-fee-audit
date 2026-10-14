-- One row per provider invoice with rule findings: what can still be disputed, by when. Overcharges are disputed;
-- undercharges are reported but never disputed; `rounding` findings are neither.
with findings as (
    select *
    from {{ ref('fct_findings') }}
    where method = 'rule' and finding_type <> 'rounding'
)

select
    coalesce(invoice_id, counterparty || ':' || strftime(statement_month, '%Y-%m')) as dispute_queue_id,
    counterparty as provider,
    invoice_id,
    statement_month,
    min(invoice_date) as invoice_date,
    min(dispute_deadline) as earliest_deadline,
    min(days_left) as days_left,
    case when min(days_left) >= 0 then 'open' else 'expired' end as status,
    count(*) filter (where difference_minor > 0) as overcharge_findings,
    coalesce(sum(difference_minor) filter (where difference_minor > 0), 0) as overcharge_minor,
    count(*) filter (where difference_minor > 0 and days_left >= 0) as open_findings,
    coalesce(sum(difference_minor) filter (where difference_minor > 0 and days_left >= 0), 0) as recoverable_minor,
    count(*) filter (where difference_minor < 0) as undercharge_findings,
    coalesce(sum(difference_minor) filter (where difference_minor < 0), 0) as undercharge_minor,
    list_sort(list(distinct finding_type)) as finding_types,
    min(currency) as currency
from findings
group by all
