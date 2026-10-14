-- Every provider line ends up in exactly one reconciliation status, and int_reconciliation has no line that
-- int_provider_lines does not know.
with lines as (
    select distinct line_id from {{ ref('int_provider_lines') }}
),

statuses as (
    select line_id, count(*) as status_rows, count(status) as statuses
    from {{ ref('int_reconciliation') }}
    where line_id is not null
    group by line_id
)

select coalesce(l.line_id, s.line_id) as line_id, s.status_rows, s.statuses
from lines as l
full outer join statuses as s on s.line_id = l.line_id
where l.line_id is null or s.line_id is null or s.status_rows <> 1 or s.statuses <> 1
