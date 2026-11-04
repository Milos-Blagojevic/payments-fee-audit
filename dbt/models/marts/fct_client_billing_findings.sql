-- Client billing findings: every client invoice line (client × month × component) whose billed
-- amount differs from the pricing agreement by at least one minor unit. Same columns as `fct_findings` with
-- party `client`; `component` is the invoice line component. Negative differences are revenue leakage: Fernway
-- billed too little and corrects its own invoice; nothing is disputed with a provider (A31).
select
    md5(concat_ws(
        '|', 'rule', 'client', c.client_id, c.finding_type, strftime(c.month, '%Y-%m'), '', c.component,
        array_to_string(c.line_ids, ',')
    )) as finding_id,
    'client' as party,
    c.client_id as counterparty,
    c.finding_type,
    c.month,
    cast(null as varchar) as event_id,
    c.line_ids,
    c.component,
    c.contract_id,
    c.contract_version,
    c.clause,
    c.expected_minor,
    c.billed_minor,
    c.difference_minor,
    c.currency,
    case when c.difference_minor > 0 then 'over' else 'under' end as direction,
    c.formula,
    c.evidence,
    c.month as statement_month,
    c.invoice_id,
    c.invoice_date,
    cast(c.invoice_date + c.dispute_window_days as date) as dispute_deadline,
    cast(c.invoice_date + c.dispute_window_days as date) - cast('{{ var("as_of_date") }}' as date) as days_left,
    'rule' as method
from {{ ref('int_client_billing_comparison') }} as c
where c.finding_type is not null
