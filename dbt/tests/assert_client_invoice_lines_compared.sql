-- Every client invoice line is compared exactly once, the compared amounts add up to each invoice's total, and
-- every client finding is at least one minor unit.
with invoice_lines as (
    select invoice_line_id from {{ ref('stg_fernway__client_invoice_lines') }}
),

compared_lines as (
    select unnest(line_ids) as invoice_line_id, client_billing_line_id
    from {{ ref('int_client_billing_comparison') }}
),

line_counts as (
    select l.invoice_line_id, count(c.client_billing_line_id) as comparisons
    from invoice_lines as l
    left join compared_lines as c on c.invoice_line_id = l.invoice_line_id
    group by l.invoice_line_id
),

invoice_totals as (
    select i.invoice_id, i.total_minor, sum(c.billed_minor) as compared_minor
    from {{ ref('stg_fernway__client_invoices') }} as i
    left join {{ ref('int_client_billing_comparison') }} as c
        on c.client_id = i.client_id and c.month = i.period_month
    group by i.invoice_id, i.total_minor
)

select invoice_line_id as unit, 'compared ' || comparisons || ' times' as problem
from line_counts
where comparisons <> 1

union all

select c.invoice_line_id, 'not an invoice line'
from compared_lines as c
where c.invoice_line_id not in (select invoice_line_id from invoice_lines)

union all

select invoice_id, 'total ' || total_minor || ' <> compared ' || coalesce(compared_minor, 0)
from invoice_totals
where total_minor <> coalesce(compared_minor, 0)

union all

select finding_id, 'below one minor unit'
from {{ ref('fct_client_billing_findings') }}
where abs(difference_minor) < 1
