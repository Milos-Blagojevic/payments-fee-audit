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
),

-- What the same statement should have billed: expected invoiced charges of the events (and months) it covers.
-- Lines that are pending (ledger lag) have no expectation yet and are counted separately.
statement_expected as (
    select
        provider,
        statement_month,
        sum(expected_minor) filter (where comparison_status = 'compared') as expected_total_minor,
        sum(billed_minor) filter (where comparison_status = 'pending') as pending_billed_minor
    from {{ ref('int_charge_comparison') }}
    where component <> 'fx_conversion'
    group by provider, statement_month
),

statement_findings as (
    select
        counterparty as provider,
        statement_month,
        count(*) filter (where finding_type <> 'rounding') as findings,
        coalesce(sum(difference_minor) filter (where finding_type <> 'rounding'), 0) as findings_total_minor,
        coalesce(sum(difference_minor) filter (where finding_type = 'rounding'), 0) as rounding_total_minor
    from {{ ref('fct_findings') }}
    group by counterparty, statement_month
),

reconciled as (
    select
        coalesce(i.provider, s.provider) as provider,
        coalesce(i.statement_month, s.statement_month) as statement_month,
        i.invoice_id,
        i.invoice_date,
        coalesce(i.currency, 'EUR') as currency,
        i.total_minor as invoice_total_minor,
        coalesce(s.lines_total_minor, 0) as lines_total_minor,
        coalesce(s.line_count, 0) as line_count,
        i.source_file,
        i.source_row
    from invoices as i
    full outer join statement_lines as s
        on s.provider = i.provider and s.statement_month = i.statement_month
)

select
    r.provider || ':' || strftime(r.statement_month, '%Y-%m') as invoice_reconciliation_id,
    r.provider,
    r.statement_month,
    r.invoice_id,
    r.invoice_date,
    r.currency,
    r.invoice_total_minor,
    r.lines_total_minor,
    r.line_count,
    coalesce(r.invoice_total_minor, 0) - r.lines_total_minor as invoice_difference_minor,
    coalesce(e.expected_total_minor, 0) as expected_total_minor,
    coalesce(e.pending_billed_minor, 0) as pending_billed_minor,
    r.lines_total_minor - coalesce(e.pending_billed_minor, 0) - coalesce(e.expected_total_minor, 0)
        as billed_minus_expected_minor,
    coalesce(f.findings, 0) as findings,
    coalesce(f.findings_total_minor, 0) as findings_total_minor,
    coalesce(f.rounding_total_minor, 0) as rounding_total_minor,
    r.source_file,
    r.source_row
from reconciled as r
left join statement_expected as e on e.provider = r.provider and e.statement_month = r.statement_month
left join statement_findings as f on f.provider = r.provider and f.statement_month = r.statement_month
