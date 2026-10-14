---
title: Evaluation
sidebar_position: 7
---

Synthetic data. Because the data is generated, every planted billing error is known. The evaluation step (`make eval`) matches the findings against that ground truth after the checks have run; the checks never read it. Precision is the share of findings of a type that match a planted error; recall is the share of planted errors that were found.

```sql detection
select
    truth_id,
    finding_type,
    planted,
    found,
    findings,
    true_positives,
    precision,
    recall,
    planted_minor / 100.0 as planted_eur,
    found_minor / 100.0 as found_eur,
    money_recall
from fees.detection_by_type
order by truth_id
```

```sql detection_totals
select
    min(precision) as min_precision,
    min(recall) as min_recall,
    sum(abs(found_eur)) / nullif(sum(abs(planted_eur)), 0) as money_recall,
    sum(planted) as planted,
    sum(found) as found
from ${detection}
```

```sql noise
select label, findings, difference_minor / 100.0 as difference_eur
from fees.noise_summary
order by sort
```

```sql noise_fp
select findings from fees.noise_summary where category = 'noise'
```

<BigValue data={detection_totals} value=min_precision fmt=pct1 title="Lowest precision of any type"/>
<BigValue data={detection_totals} value=min_recall fmt=pct1 title="Lowest recall of any type"/>
<BigValue data={detection_totals} value=money_recall fmt=pct2 title="Money recall, all types"/>
<BigValue data={noise_fp} value=findings fmt=num0 title="Noise false positives"/>

## Precision and recall by type

<BarChart
    data={detection}
    x=finding_type
    y={['precision', 'recall']}
    type=grouped
    swapXY=true
    yFmt=pct0
    yMin=0
    yMax=1
    sort=false
    title="Precision and recall by planted error type"
/>

<DataTable data={detection} rows=all wrapTitles=true>
    <Column id=truth_id title="Id"/>
    <Column id=finding_type title="Finding type"/>
    <Column id=planted title="Planted" fmt=num0 totalAgg=sum/>
    <Column id=found title="Found" fmt=num0 totalAgg=sum/>
    <Column id=findings title="Findings" fmt=num0 totalAgg=sum/>
    <Column id=true_positives title="True positives" fmt=num0 totalAgg=sum/>
    <Column id=precision title="Precision" fmt=pct1/>
    <Column id=recall title="Recall" fmt=pct1/>
    <Column id=planted_eur title="Planted amount" fmt=eur2 totalAgg=sum/>
    <Column id=found_eur title="Found amount" fmt=eur2 totalAgg=sum/>
    <Column id=money_recall title="Money recall" fmt=pct1/>
</DataTable>

## Noise

The generator also plants noise: messy but correctly billed data, such as re-exported duplicate rows, mixed number formats, local timestamps and lines without a provider reference. A finding on a noise row is a false positive.

<DataTable data={noise} rows=all>
    <Column id=label title="Category"/>
    <Column id=findings title="Findings" fmt=num0/>
    <Column id=difference_eur title="Amount" fmt=eur2/>
</DataTable>

## Planted against found, per provider and month

```sql invoice_level
select provider, month, planted, findings, planted_minor / 100.0 as planted_eur,
       findings_minor / 100.0 as findings_eur, gap_minor / 100.0 as gap_eur
from fees.invoice_level
order by provider, month
```

<DataTable data={invoice_level} rows=all wrapTitles=true>
    <Column id=provider title="Provider"/>
    <Column id=month title="Month"/>
    <Column id=planted title="Planted" fmt=num0 totalAgg=sum/>
    <Column id=findings title="Findings" fmt=num0 totalAgg=sum/>
    <Column id=planted_eur title="Planted amount" fmt=eur2 totalAgg=sum/>
    <Column id=findings_eur title="Findings amount" fmt=eur2 totalAgg=sum/>
    <Column id=gap_eur title="Found − planted" fmt=eur2 totalAgg=sum/>
</DataTable>
