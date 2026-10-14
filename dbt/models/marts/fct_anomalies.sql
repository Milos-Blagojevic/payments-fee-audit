{#-
    Anomalies (spec section 10): billing patterns that no rule describes. Two kinds:
    - `rate_shift`: a day whose effective rate of a provider × fee component × card segment is beyond the robust
      z-score threshold against its trailing median (int_daily_component_rates, A10, A42);
    - `new_component`: the first day a provider bills a fee component that no version of its contract names and
      that it did not bill in its first `anomaly_window_days` days (A43).
    `explained_by` says whether the day's money is already accounted for: by rule findings on the same charges, or
    by the contract itself (every charge equals its expected amount, as on a new tier or contract version). Only
    unexplained anomalies become findings with `method = 'anomaly'` in fct_findings (A44).
-#}
{% set window_days = var('anomaly_window_days') %}

with rates as (
    select * from {{ ref('int_daily_component_rates') }}
),

rate_shifts as (
    select
        'rate_shift' as anomaly_type,
        provider,
        component,
        card_segment,
        day,
        volume_minor,
        billed_minor,
        line_count,
        rate_bps as observed_rate_bps,
        baseline_median_bps as baseline_rate_bps,
        baseline_days,
        mad_bps,
        mean_absolute_deviation_bps,
        scoring_method,
        robust_z,
        z_threshold,
        rule_finding_charges,
        rule_difference_minor,
        unexplained_minor,
        unexplained_line_ids,
        unexplained_source_files,
        unexplained_statement_month,
        component_has_term
    from rates
    where is_anomaly
),

-- Every compared charge that was billed on at least one line, dated by its event (month-level charges by their
-- month), for the first appearance of each provider × component.
billed as (
    select
        provider,
        component,
        coalesce(cast(event_timestamp_utc as date), month) as day,
        billed_minor,
        expected_minor,
        finding_type,
        line_ids,
        evidence,
        statement_month,
        component_has_term
    from {{ ref('int_charge_comparison') }}
    where comparison_status = 'compared' and len(line_ids) > 0
),

provider_history as (
    select provider, min(day) as first_day
    from billed
    group by provider
),

first_appearances as (
    select b.provider, b.component, min(b.day) as day
    from billed as b
    group by all
    having not bool_or(b.component_has_term)
),

new_components as (
    select
        'new_component' as anomaly_type,
        b.provider,
        b.component,
        'all' as card_segment,
        b.day,
        max(v.volume_minor) as volume_minor,
        sum(b.billed_minor) as billed_minor,
        sum(len(b.line_ids)) as line_count,
        {{ rate_bps('sum(b.billed_minor)', 'max(v.volume_minor)') }} as observed_rate_bps,
        cast(0 as decimal(18, 6)) as baseline_rate_bps,
        max(b.day - h.first_day) as baseline_days,
        cast(null as decimal(18, 6)) as mad_bps,
        cast(null as decimal(18, 6)) as mean_absolute_deviation_bps,
        'first_appearance' as scoring_method,
        cast(null as double) as robust_z,
        cast(null as integer) as z_threshold,
        count(*) filter (where b.finding_type is not null) as rule_finding_charges,
        coalesce(sum(b.billed_minor - b.expected_minor) filter (where b.finding_type is not null), 0)
            as rule_difference_minor,
        coalesce(sum(b.billed_minor - b.expected_minor) filter (where b.finding_type is null), 0) as unexplained_minor,
        list_sort(flatten(list(b.line_ids) filter (where b.finding_type is null and b.billed_minor <> b.expected_minor)))
            as unexplained_line_ids,
        string_agg(distinct split_part(b.evidence, ':', 1), ', ' order by split_part(b.evidence, ':', 1))
            filter (where b.finding_type is null and b.billed_minor <> b.expected_minor) as unexplained_source_files,
        min(b.statement_month) filter (where b.finding_type is null and b.billed_minor <> b.expected_minor)
            as unexplained_statement_month,
        false as component_has_term
    from first_appearances as f
    inner join provider_history as h on h.provider = f.provider
    inner join billed as b on b.provider = f.provider and b.component = f.component and b.day = f.day
    -- M01 of the provider's whole volume that day (all card segments); null for a payout provider.
    left join (
        select provider, cast(event_timestamp_utc as date) as day, sum(amount_minor) as volume_minor
        from {{ ref('int_ledger_events') }}
        where event_type = 'payment' and payment_status = 'succeeded'
        group by all
    ) as v on v.provider = b.provider and v.day = b.day
    where f.day >= h.first_day + {{ window_days }}
    group by all
),

anomalies as (
    select * from rate_shifts
    union all by name
    select * from new_components
),

explained as (
    select
        *,
        case
            when unexplained_minor = 0 and rule_finding_charges > 0 then 'rule_findings'
            when unexplained_minor = 0 then 'contract'
        end as explained_by
    from anomalies
)

select
    anomaly_type || ':' || provider || ':' || component || ':' || card_segment || ':' || strftime(day, '%Y-%m-%d')
        as anomaly_id,
    anomaly_type,
    provider,
    component,
    card_segment,
    day,
    cast(date_trunc('month', day) as date) as month,
    observed_rate_bps,
    baseline_rate_bps,
    baseline_days,
    mad_bps,
    mean_absolute_deviation_bps,
    scoring_method,
    robust_z,
    z_threshold,
    volume_minor,
    billed_minor,
    -- What the baseline rate would have billed on the day's volume (0 for a new component).
    case
        when volume_minor is null then 0
        else {{ round_half_up('volume_minor * cast(baseline_rate_bps * 1000000 as hugeint)', '10000000000') }}
    end as baseline_minor,
    line_count,
    rule_finding_charges,
    rule_difference_minor,
    unexplained_minor,
    unexplained_line_ids,
    unexplained_source_files,
    unexplained_statement_month,
    component_has_term,
    explained_by,
    explained_by is null as is_finding,
    case anomaly_type
        when 'new_component' then
            provider || ' bills ' || component || ' for the first time on ' || strftime(day, '%Y-%m-%d') || ': '
            || format('{:,}', line_count) || ' lines, ' || {{ fmt_money('billed_minor') }} || ' EUR'
            || coalesce(
                ' (' || cast(round(observed_rate_bps, 2) as varchar) || ' bps of the day''s processed volume of '
                || {{ fmt_money('volume_minor') }} || ' EUR)',
                ''
            )
            || '. Baseline: 0 bps, it was never billed in the ' || baseline_days
            || ' days of history before, and no version of the ' || provider
            || ' contract names it. Threshold: any amount of a fee type never seen before.'
        else
            provider || ' ' || component || ' on ' || card_segment || ' cards on ' || strftime(day, '%Y-%m-%d')
            || ': observed ' || cast(round(observed_rate_bps, 2) as varchar) || ' bps of the day''s processed volume ('
            || {{ fmt_money('billed_minor') }} || ' EUR on ' || {{ fmt_money('volume_minor') }} || ' EUR). Baseline: median '
            || cast(round(baseline_rate_bps, 2) as varchar) || ' bps over the previous ' || baseline_days || ' days'
            || case scoring_method
                when 'mad' then ', MAD ' || cast(round(mad_bps, 2) as varchar) || ' bps; robust z = 0.6745 × (observed − median) ÷ MAD = '
                    || cast(robust_z as varchar)
                when 'mean_absolute_deviation' then '; the MAD is 0, so z = (observed − median) ÷ (1.2533 × mean absolute deviation '
                    || cast(round(mean_absolute_deviation_bps, 2) as varchar) || ' bps) = ' || cast(robust_z as varchar)
                else '; every baseline day had this same rate, so any other rate is flagged'
            end
            || '. Threshold: |z| above ' || z_threshold || '.'
    end
    || case
        when explained_by = 'rule_findings' then ' Explained by rule findings on ' || rule_finding_charges
            || ' of the day''s charges (' || {{ fmt_money('rule_difference_minor') }}
            || ' EUR beyond the contract); every other charge equals the contract.'
        when explained_by = 'contract' then ' Explained by the contract: every charge of the day equals its expected'
            || ' amount (a new tier, contract version or volume mix).'
        else ' Not explained: ' || {{ fmt_money('unexplained_minor') }}
            || ' EUR billed that neither the contract nor a rule finding accounts for.'
    end as explanation
from explained
