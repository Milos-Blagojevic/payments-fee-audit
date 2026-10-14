-- Every provider line component lands in exactly one int_charge_comparison row, and the comparison bills exactly
-- what the provider lines bill.
with compared_lines as (
    select unnest(line_ids) as line_id, component
    from {{ ref('int_charge_comparison') }}
),

counts as (
    select line_id || ':' || component as line_component_id, count(*) as rows_with_line
    from compared_lines
    group by all
)

select l.line_component_id, c.rows_with_line
from {{ ref('int_provider_lines') }} as l
full outer join counts as c on c.line_component_id = l.line_component_id
where l.line_component_id is null or c.line_component_id is null or c.rows_with_line <> 1

union all

select 'total billed', null
from (select sum(billed_minor) as total from {{ ref('int_charge_comparison') }}) as c
cross join (select sum(amount_minor) as total from {{ ref('int_provider_lines') }}) as l
where c.total is distinct from l.total
