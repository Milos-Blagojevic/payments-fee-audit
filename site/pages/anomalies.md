---
title: Anomalies
sidebar_position: 8
---

Synthetic data; contract rates are illustrative. The rules check every charge against a contract term. The anomaly model looks for billing patterns no rule describes:

- **Rate shift**: a day on which the fees of one provider × fee component × card segment, as basis points of the day's processed volume, sit beyond the robust z-score threshold against the median of the trailing window.
- **New component**: the first day a provider bills a fee component that no version of its contract names.

Each anomaly is then explained if possible: by **rule findings** on the same charges (the shift is money the rules already report) or by the **contract** (every charge equals its expected amount, as on a new tier or contract version). Only unexplained anomalies become findings (`method = anomaly` on the [Findings](/findings) page).

```sql summary
select
    count(*) as anomalies,
    count(*) filter (where explained_by = 'rule_findings') as by_rule_findings,
    count(*) filter (where explained_by = 'contract') as by_contract,
    count(*) filter (where is_finding) as findings,
    coalesce(sum(unexplained_minor) filter (where is_finding), 0) / 100.0 as unexplained_eur
from fees.anomalies
```

<BigValue data={summary} value=anomalies fmt=num0 title="Anomalies"/>
<BigValue data={summary} value=by_rule_findings fmt=num0 title="Explained by rule findings"/>
<BigValue data={summary} value=by_contract fmt=num0 title="Explained by the contract"/>
<BigValue data={summary} value=findings fmt=num0 title="Unexplained (findings)"/>
<BigValue data={summary} value=unexplained_eur fmt=eur2 title="Unexplained amount"/>

## Planted pattern

The generator plants anomaly patterns that no contract term or rule covers. This table shows each plant and whether, when and how the model detected it.

```sql planted
select
    anomaly_id,
    provider,
    component,
    card_segment,
    line_type,
    rate_bps,
    start_date,
    planted_lines,
    planted_minor / 100.0 as planted_eur,
    detected,
    first_detected_day,
    days_to_detect,
    anomaly_type,
    detections,
    explained_by,
    is_finding,
    explanation
from fees.anomaly_report
where category = 'planted'
order by anomaly_id
```

```sql not_planted
select
    count(*) as detections,
    count(*) filter (where is_finding) as findings
from fees.anomaly_report
where category = 'not_planted'
```

<DataTable data={planted} rows=all wrapTitles=true>
    <Column id=anomaly_id title="Plant"/>
    <Column id=provider title="Provider"/>
    <Column id=component title="Component"/>
    <Column id=rate_bps title="Rate (bps)" fmt=num0/>
    <Column id=start_date title="Starts"/>
    <Column id=planted_lines title="Lines planted" fmt=num0/>
    <Column id=planted_eur title="Amount planted" fmt=eur2/>
    <Column id=detected title="Detected"/>
    <Column id=first_detected_day title="First detected"/>
    <Column id=days_to_detect title="Days to detect" fmt=num0/>
    <Column id=anomaly_type title="Detected as"/>
    <Column id=explained_by title="Explained by"/>
    <Column id=is_finding title="Finding"/>
</DataTable>

{#each planted as plant}

**{plant.anomaly_id}**: {plant.explanation}

{/each}

Detections that match no plant: <Value data={not_planted} column=detections fmt=num0/>, of which <Value data={not_planted} column=findings fmt=num0/> unexplained. Each row of the table below states why it is or is not a finding.

## Anomalies

```sql explanations
select distinct explained_by from fees.anomalies order by explained_by
```

```sql anomaly_providers
select distinct provider from fees.anomalies order by provider
```

<Dropdown data={explanations} name=explained value=explained_by title="Explained by" defaultValue="%">
    <DropdownOption value="%" valueLabel="All"/>
</Dropdown>

<Dropdown data={anomaly_providers} name=provider value=provider title="Provider" defaultValue="%">
    <DropdownOption value="%" valueLabel="All providers"/>
</Dropdown>

```sql filtered
select
    day,
    month_label,
    anomaly_type,
    provider,
    component,
    card_segment,
    baseline_rate_bps,
    observed_rate_bps,
    scoring_method,
    robust_z,
    z_threshold,
    baseline_days,
    billed_minor / 100.0 as billed_eur,
    baseline_minor / 100.0 as baseline_eur,
    rule_finding_charges,
    rule_difference_minor / 100.0 as rule_difference_eur,
    unexplained_minor / 100.0 as unexplained_eur,
    explained_by,
    is_finding,
    explanation,
    anomaly_id
from fees.anomalies
where explained_by like '${inputs.explained.value}'
  and provider like '${inputs.provider.value}'
order by day, provider, component, card_segment
```

```sql by_month
select month_label as month, explained_by, count(*) as anomalies
from ${filtered}
group by all
order by month
```

<BarChart
    data={by_month}
    x=month
    y=anomalies
    series=explained_by
    sort=false
    yFmt=num0
    title="Anomalies by month and explanation"
/>

<ScatterPlot
    data={filtered}
    x=baseline_rate_bps
    y=observed_rate_bps
    series=explained_by
    xFmt=num1
    yFmt=num1
    xAxisTitle="baseline (bps)"
    yAxisTitle="observed (bps)"
    title="Observed against baseline rate"
/>

<DataTable data={filtered} rows=15 search=true wrapTitles=true downloadable=true>
    <Column id=day title="Day"/>
    <Column id=anomaly_type title="Type"/>
    <Column id=provider title="Provider"/>
    <Column id=component title="Component"/>
    <Column id=card_segment title="Card segment"/>
    <Column id=baseline_rate_bps title="Baseline (bps)" fmt=num2/>
    <Column id=observed_rate_bps title="Observed (bps)" fmt=num2/>
    <Column id=robust_z title="Robust z" fmt=num1/>
    <Column id=z_threshold title="Threshold |z|" fmt=num0/>
    <Column id=scoring_method title="Scale"/>
    <Column id=billed_eur title="Billed" fmt=eur2/>
    <Column id=baseline_eur title="At baseline" fmt=eur2/>
    <Column id=rule_difference_eur title="Rule findings" fmt=eur2/>
    <Column id=unexplained_eur title="Unexplained" fmt=eur2/>
    <Column id=explained_by title="Explained by"/>
</DataTable>

### Explanations

Baseline, observed value, threshold and explanation of each anomaly in plain words.

<DataTable data={filtered} rows=10 search=true>
    <Column id=day title="Day"/>
    <Column id=provider title="Provider"/>
    <Column id=component title="Component"/>
    <Column id=card_segment title="Card segment"/>
    <Column id=explanation title="Explanation" wrap=true/>
</DataTable>
