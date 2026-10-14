-- One row per provider × statement month (main.fct_invoice_reconciliation).
select
    invoice_reconciliation_id,
    provider,
    statement_month,
    strftime(statement_month, '%Y-%m') as month_label,
    invoice_id,
    invoice_date,
    currency,
    invoice_total_minor,
    lines_total_minor::bigint as lines_total_minor,
    line_count,
    invoice_difference_minor::bigint as invoice_difference_minor,
    expected_total_minor::bigint as expected_total_minor,
    pending_billed_minor::bigint as pending_billed_minor,
    billed_minus_expected_minor::bigint as billed_minus_expected_minor,
    findings,
    findings_total_minor::bigint as findings_total_minor,
    rounding_total_minor::bigint as rounding_total_minor
from main.fct_invoice_reconciliation
