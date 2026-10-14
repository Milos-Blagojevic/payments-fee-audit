-- Rule findings: every compared charge whose billed amount differs from the contract by at least one minor unit
-- and that a rule classifies (data contract section 5). The retroactive-tier pattern (D02) is one finding per
-- provider × month; every other finding is one line or event × component.
with comparison as (
    select
        *,
        billed_minor - finding_expected_minor as finding_difference_minor
    from {{ ref('int_charge_comparison') }}
    where comparison_status = 'compared' and finding_type is not null
),

line_findings as (
    select
        provider,
        finding_type,
        month,
        event_id,
        line_ids,
        component,
        contract_id,
        contract_version,
        clause,
        finding_expected_minor as expected_minor,
        billed_minor,
        finding_difference_minor as difference_minor,
        currency,
        finding_formula as formula,
        evidence,
        statement_month,
        dispute_window_days
    from comparison
    where finding_type <> 'retroactive_tier_not_applied' and abs(finding_difference_minor) >= 1
),

-- D02 is a month-level pattern: it needs the whole month's volume, so it is pending until the ledger covers
-- the month (A19).
tier_lines as (
    select c.*
    from comparison as c
    inner join {{ ref('int_provider_months') }} as m on m.provider = c.provider and m.provider_month = c.month
    where c.finding_type = 'retroactive_tier_not_applied' and m.ledger_covers_month
),

tier_findings as (
    select
        t.provider,
        'retroactive_tier_not_applied' as finding_type,
        t.month,
        cast(null as varchar) as event_id,
        list_sort(flatten(list(t.line_ids))) as line_ids,
        'markup' as component,
        min(t.contract_id) as contract_id,
        min(t.contract_version) as contract_version,
        min(t.clause) as clause,
        sum(t.finding_expected_minor) as expected_minor,
        sum(t.billed_minor) as billed_minor,
        sum(t.finding_difference_minor) as difference_minor,
        min(t.currency) as currency,
        count(*) || ' markup lines billed at the first tier rate ' || {{ fmt_bps('min(t.first_tier_bps)') }}
            || ' instead of the month''s tier ' || min(t.tier_no) || ' rate ' || {{ fmt_bps('min(t.rate_bps)') }}
            || ' (retroactive: the whole month''s volume ' || {{ fmt_money('min(m.volume_minor)') }} || ' '
            || min(t.currency) || ' sets the rate of every payment): expected ' || {{ fmt_money('sum(t.finding_expected_minor)') }}
            || ', billed ' || {{ fmt_money('sum(t.billed_minor)') }} || ' ' || min(t.currency) || ' ('
            || {{ fmt_clause('min(t.contract_id)', 'min(t.contract_version)', 'min(t.clause)') }} || ')' as formula,
        count(*) || ' MARKUP lines in ' || string_agg(distinct split_part(t.evidence, ':', 1), ', ')
            || '; ledger payments of ' || strftime(t.month, '%Y-%m') || ' (month volume); '
            || min(v.source_file) || ' §' || min(t.clause) as evidence,
        t.month as statement_month,
        min(t.dispute_window_days) as dispute_window_days
    from tier_lines as t
    inner join {{ ref('int_provider_months') }} as m on m.provider = t.provider and m.provider_month = t.month
    left join {{ ref('int_provider_contract_versions') }} as v
        on v.contract_id = t.contract_id and v.contract_version = t.contract_version
    group by t.provider, t.month
    having abs(sum(t.finding_difference_minor)) >= 1
),

findings as (
    select * from line_findings
    union all by name
    select * from tier_findings
)

select
    md5(concat_ws(
        '|', 'rule', 'provider', f.provider, f.finding_type, strftime(f.month, '%Y-%m'), coalesce(f.event_id, ''),
        f.component, array_to_string(f.line_ids, ',')
    )) as finding_id,
    'provider' as party,
    f.provider as counterparty,
    f.finding_type,
    f.month,
    f.event_id,
    f.line_ids,
    f.component,
    f.contract_id,
    f.contract_version,
    f.clause,
    f.expected_minor,
    f.billed_minor,
    f.difference_minor,
    f.currency,
    case when f.difference_minor > 0 then 'over' else 'under' end as direction,
    f.formula,
    f.evidence,
    f.statement_month,
    i.invoice_id,
    i.invoice_date,
    cast(i.invoice_date + f.dispute_window_days as date) as dispute_deadline,
    cast(i.invoice_date + f.dispute_window_days as date) - cast('{{ var("as_of_date") }}' as date) as days_left,
    'rule' as method
from findings as f
left join {{ ref('int_provider_invoices') }} as i
    on i.provider = f.provider and i.statement_month = f.statement_month
