-- Client billing findings (main.fct_client_billing_findings): L01–L04; negative = revenue leakage.
select
    finding_id,
    counterparty as client_id,
    finding_type,
    month,
    strftime(month, '%Y-%m') as month_label,
    component,
    contract_id || ' v' || contract_version::varchar || ' §' || clause as term,
    expected_minor::bigint as expected_minor,
    billed_minor::bigint as billed_minor,
    difference_minor::bigint as difference_minor,
    currency,
    direction,
    formula,
    evidence,
    array_to_string(line_ids, ', ') as line_ids,
    invoice_id,
    invoice_date,
    dispute_deadline,
    days_left,
    method
from main.fct_client_billing_findings
