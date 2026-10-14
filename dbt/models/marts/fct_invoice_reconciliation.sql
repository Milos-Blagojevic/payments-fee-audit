with invoices as (
    select * from {{ ref('int_provider_invoices') }}
),

-- What each statement (file month) billed: every distinct invoiced line, N01 re-exports already removed.
statement_lines as (
    select
        provider,
        statement_month,
        count(distinct line_id) as line_count,
        sum(amount_minor) as lines_total_minor
    from {{ ref('int_provider_lines') }}
    where is_invoiced
    group by provider, statement_month
)

select
    coalesce(i.provider, s.provider) || ':' || strftime(coalesce(i.statement_month, s.statement_month), '%Y-%m')
        as invoice_reconciliation_id,
    coalesce(i.provider, s.provider) as provider,
    coalesce(i.statement_month, s.statement_month) as statement_month,
    i.invoice_id,
    i.invoice_date,
    coalesce(i.currency, 'EUR') as currency,
    i.total_minor as invoice_total_minor,
    coalesce(s.lines_total_minor, 0) as lines_total_minor,
    coalesce(s.line_count, 0) as line_count,
    coalesce(i.total_minor, 0) - coalesce(s.lines_total_minor, 0) as invoice_difference_minor,
    i.source_file,
    i.source_row
from invoices as i
full outer join statement_lines as s
    on s.provider = i.provider and s.statement_month = i.statement_month
