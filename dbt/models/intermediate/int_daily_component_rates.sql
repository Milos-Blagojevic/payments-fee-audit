{#-
    Daily effective rate per provider × fee component × card segment (spec section 10, A10): what the day's card
    events were billed for that component, in basis points of the day's processed volume (M01 by UTC day), against
    the median and the median absolute deviation (MAD) of the same series over the previous
    `anomaly_window_days` days. A day is scored once that window holds `anomaly_window_days` observed days.
    Robust z = 0.6745 × (rate − median) ÷ MAD; when MAD = 0 the score falls back to the mean absolute deviation,
    (rate − median) ÷ (1.2533 × mean AD); when both are 0 the baseline is constant and any other rate is flagged
    (A42). The flag uses |z| > `anomaly_z_threshold`.
-#}
{% set window_days = var('anomaly_window_days') %}
{% set threshold = var('anomaly_z_threshold') %}

-- Compared charges of card events with a card segment: billed lines and expected charges of payments, refunds
-- and chargebacks that are in the ledger. Pending charges (after the ledger watermark) wait.
with charges as (
    select
        provider,
        component,
        card_segment,
        cast(event_timestamp_utc as date) as day,
        billed_minor,
        expected_minor,
        finding_type,
        line_ids,
        evidence,
        statement_month,
        component_has_term
    from {{ ref('int_charge_comparison') }}
    where comparison_status = 'compared'
        and event_type in ('payment', 'refund', 'chargeback')
        and card_segment is not null
),

daily_charges as (
    select
        provider,
        component,
        card_segment,
        day,
        sum(billed_minor) as billed_minor,
        sum(expected_minor) as expected_minor,
        sum(len(line_ids)) as line_count,
        count(*) filter (where finding_type is not null) as rule_finding_charges,
        coalesce(sum(billed_minor - expected_minor) filter (where finding_type is not null), 0) as rule_difference_minor,
        -- Money neither a rule finding nor the contract accounts for (a component no term names, for example).
        coalesce(sum(billed_minor - expected_minor) filter (where finding_type is null), 0) as unexplained_minor,
        list_sort(flatten(list(line_ids) filter (where finding_type is null and billed_minor <> expected_minor)))
            as unexplained_line_ids,
        string_agg(distinct split_part(evidence, ':', 1), ', ' order by split_part(evidence, ':', 1))
            filter (where finding_type is null and billed_minor <> expected_minor) as unexplained_source_files,
        min(statement_month) filter (where finding_type is null and billed_minor <> expected_minor)
            as unexplained_statement_month,
        bool_or(component_has_term) as component_has_term
    from charges
    group by all
),

-- M01 by provider × card segment × UTC day.
daily_volumes as (
    select provider, card_segment, cast(event_timestamp_utc as date) as day, sum(amount_minor) as volume_minor
    from {{ ref('int_ledger_events') }}
    where event_type = 'payment' and payment_status = 'succeeded'
    group by all
),

-- A series starts on the first day a line of it is billed; from then on every day with volume is a data point
-- (a day without lines has rate 0).
series as (
    select provider, component, card_segment, min(day) as first_day
    from daily_charges
    where line_count > 0
    group by all
),

days as (
    select
        s.provider,
        s.component,
        s.card_segment,
        v.day,
        v.volume_minor,
        coalesce(c.billed_minor, 0) as billed_minor,
        coalesce(c.expected_minor, 0) as expected_minor,
        coalesce(c.line_count, 0) as line_count,
        coalesce(c.rule_finding_charges, 0) as rule_finding_charges,
        coalesce(c.rule_difference_minor, 0) as rule_difference_minor,
        coalesce(c.unexplained_minor, 0) as unexplained_minor,
        coalesce(c.unexplained_line_ids, []::varchar[]) as unexplained_line_ids,
        c.unexplained_source_files,
        c.unexplained_statement_month,
        coalesce(c.component_has_term, false) as component_has_term,
        {{ rate_bps('coalesce(c.billed_minor, 0)', 'v.volume_minor') }} as rate_bps,
        {{ rate_bps('coalesce(c.expected_minor, 0)', 'v.volume_minor') }} as expected_rate_bps
    from series as s
    inner join daily_volumes as v
        on v.provider = s.provider and v.card_segment = s.card_segment and v.day >= s.first_day
    left join daily_charges as c
        on c.provider = s.provider and c.component = s.component and c.card_segment = s.card_segment and c.day = v.day
),

windows as (
    select d.provider, d.component, d.card_segment, d.day, w.rate_bps as baseline_rate_bps
    from days as d
    inner join days as w
        on w.provider = d.provider
        and w.component = d.component
        and w.card_segment = d.card_segment
        and w.day between d.day - {{ window_days }} and d.day - 1
),

medians as (
    select
        provider,
        component,
        card_segment,
        day,
        count(*) as baseline_days,
        cast(median(baseline_rate_bps) as decimal(18, 6)) as baseline_median_bps
    from windows
    group by all
),

deviations as (
    select
        m.provider,
        m.component,
        m.card_segment,
        m.day,
        m.baseline_days,
        m.baseline_median_bps,
        cast(median(abs(w.baseline_rate_bps - m.baseline_median_bps)) as decimal(18, 6)) as mad_bps,
        cast(avg(abs(w.baseline_rate_bps - m.baseline_median_bps)) as decimal(18, 6)) as mean_absolute_deviation_bps
    from medians as m
    inner join windows as w
        on w.provider = m.provider and w.component = m.component and w.card_segment = m.card_segment and w.day = m.day
    group by all
),

scored as (
    select
        d.*,
        dv.baseline_days,
        dv.baseline_median_bps,
        dv.mad_bps,
        dv.mean_absolute_deviation_bps,
        case
            when coalesce(dv.baseline_days, 0) < {{ window_days }} then null
            when dv.mad_bps > 0 then 'mad'
            when dv.mean_absolute_deviation_bps > 0 then 'mean_absolute_deviation'
            else 'constant_baseline'
        end as scoring_method
    from days as d
    left join deviations as dv
        on dv.provider = d.provider and dv.component = d.component and dv.card_segment = d.card_segment
        and dv.day = d.day
),

z as (
    select
        *,
        case scoring_method
            when 'mad' then 0.6745 * cast(rate_bps - baseline_median_bps as double) / cast(mad_bps as double)
            when 'mean_absolute_deviation'
                then cast(rate_bps - baseline_median_bps as double) / (1.253314 * cast(mean_absolute_deviation_bps as double))
        end as robust_z
    from scored
)

select
    provider || ':' || component || ':' || card_segment || ':' || strftime(day, '%Y-%m-%d') as daily_rate_id,
    provider,
    component,
    card_segment,
    day,
    volume_minor,
    billed_minor,
    expected_minor,
    line_count,
    rate_bps,
    expected_rate_bps,
    baseline_days,
    baseline_median_bps,
    mad_bps,
    mean_absolute_deviation_bps,
    scoring_method,
    round(robust_z, 2) as robust_z,
    {{ threshold }} as z_threshold,
    coalesce(
        abs(robust_z) > {{ threshold }} or (scoring_method = 'constant_baseline' and rate_bps <> baseline_median_bps),
        false
    ) as is_anomaly,
    rule_finding_charges,
    rule_difference_minor,
    unexplained_minor,
    unexplained_line_ids,
    unexplained_source_files,
    unexplained_statement_month,
    component_has_term
from z
