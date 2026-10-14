-- An anomaly finding never covers a line that a rule finding already explains (A44), and every anomaly finding
-- comes from an unexplained fct_anomalies row.
with anomaly_lines as (
    select finding_id, unnest(line_ids) as line_id
    from {{ ref('fct_findings') }}
    where method = 'anomaly'
),

rule_lines as (
    select unnest(line_ids) as line_id
    from {{ ref('fct_findings') }}
    where method = 'rule'
)

select a.finding_id, 'line already in a rule finding' as problem
from anomaly_lines as a
where a.line_id in (select line_id from rule_lines)

union all

select f.finding_id, 'no unexplained anomaly behind the finding'
from {{ ref('fct_findings') }} as f
where f.method = 'anomaly'
    and not exists (
        select 1
        from {{ ref('fct_anomalies') }} as a
        where a.is_finding and a.provider = f.counterparty and a.component = f.component
            and a.anomaly_type = f.finding_type and a.unexplained_line_ids = f.line_ids
    )
