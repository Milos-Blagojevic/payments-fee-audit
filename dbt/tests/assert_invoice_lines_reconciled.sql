-- The sum of lines per provider × statement month equals the invoice total, or the difference is reported:
-- every invoice and every statement month with lines has a row, and the reported difference is exact.
with invoices as (
    select provider, statement_month, total_minor from {{ ref('int_provider_invoices') }}
),

statements as (
    select provider, statement_month, sum(amount_minor) as lines_total_minor
    from {{ ref('int_provider_lines') }}
    where is_invoiced
    group by provider, statement_month
),

expected as (
    select
        coalesce(i.provider, s.provider) as provider,
        coalesce(i.statement_month, s.statement_month) as statement_month,
        coalesce(i.total_minor, 0) - coalesce(s.lines_total_minor, 0) as difference_minor
    from invoices as i
    full outer join statements as s on s.provider = i.provider and s.statement_month = i.statement_month
)

select e.*, r.invoice_difference_minor
from expected as e
left join {{ ref('fct_invoice_reconciliation') }} as r
    on r.provider = e.provider and r.statement_month = e.statement_month
where r.invoice_difference_minor is distinct from e.difference_minor
