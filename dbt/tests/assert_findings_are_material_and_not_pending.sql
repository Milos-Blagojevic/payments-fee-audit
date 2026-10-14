-- A finding is at least one minor unit, and nothing pending becomes a finding: no line after the ledger
-- watermark, and no provider × month rule finding for a month the ledger does not cover yet (anomaly findings are
-- per day and cover compared charges only).
with findings as (
    select * from {{ ref('fct_findings') }}
),

pending_lines as (
    select line_id from {{ ref('int_reconciliation') }} where status = 'unmatched_pending'
)

select finding_id, 'below one minor unit' as problem
from findings
where abs(difference_minor) < 1

union all

select f.finding_id, 'pending line'
from findings as f
where exists (select 1 from pending_lines as p where list_contains(f.line_ids, p.line_id))

union all

select f.finding_id, 'month not covered by the ledger'
from findings as f
inner join {{ ref('int_provider_months') }} as m on m.provider = f.counterparty and m.provider_month = f.month
where f.method = 'rule' and f.event_id is null and f.finding_type <> 'unknown_charge' and not m.ledger_covers_month
