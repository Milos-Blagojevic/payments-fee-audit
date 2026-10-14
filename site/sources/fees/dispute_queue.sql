-- One row per provider invoice with findings (main.fct_dispute_queue): M05, M06, M07.
select
    invoice_id,
    provider,
    statement_month,
    strftime(statement_month, '%Y-%m') as month_label,
    invoice_date,
    earliest_deadline,
    days_left,
    status,
    overcharge_findings,
    overcharge_minor::bigint as overcharge_minor,
    open_findings,
    recoverable_minor::bigint as recoverable_minor,
    undercharge_findings,
    undercharge_minor::bigint as undercharge_minor,
    array_to_string(finding_types, ', ') as finding_types,
    currency
from main.fct_dispute_queue
