---
title: Provider comparison
sidebar_position: 5
---

Synthetic data; contract rates are illustrative. For each card segment and UTC month, the payment-level fees of the payments a card provider processed under its own contract, against what the same payments would have cost under the other card provider's contract (assumption A23). A positive saving means the alternative contract would have been cheaper.

```sql segments
select distinct card_segment from fees.provider_comparison order by card_segment
```

<Dropdown data={segments} name=segment value=card_segment title="Card segment" defaultValue="eea_consumer"/>

```sql comparison
select
    month_label as month,
    actual_provider,
    alternative_provider,
    actual_provider || ' → ' || alternative_provider as pair,
    payments,
    volume_minor / 100.0 as volume_eur,
    actual_billed_minor / 100.0 as actual_billed_eur,
    actual_expected_minor / 100.0 as actual_expected_eur,
    alternative_expected_minor / 100.0 as alternative_expected_eur,
    saving_minor / 100.0 as saving_eur,
    actual_rate_bps,
    alternative_rate_bps
from fees.provider_comparison
where card_segment = '${inputs.segment.value}'
order by month, actual_provider
```

```sql rates_long
select month, actual_provider || ', own contract' as series, actual_rate_bps as rate_bps from ${comparison}
union all
select month, actual_provider || ', ' || alternative_provider || ' contract' as series, alternative_rate_bps as rate_bps from ${comparison}
order by month
```

```sql totals
select actual_provider, alternative_provider, sum(payments) as payments, sum(volume_eur) as volume_eur,
       sum(actual_expected_eur) as actual_expected_eur, sum(alternative_expected_eur) as alternative_expected_eur,
       sum(saving_eur) as saving_eur
from ${comparison}
group by all
order by actual_provider
```

<BarChart
    data={comparison}
    x=month
    sort=false
    y=saving_eur
    series=pair
    type=grouped
    yFmt=eur
    title="Saving under the alternative contract (actual − alternative)"
/>

<BarChart
    data={rates_long}
    x=month
    sort=false
    y=rate_bps
    series=series
    type=grouped
    yFmt=num1
    yAxisTitle="basis points"
    title="Fees ÷ volume by processing provider: own contract against the alternative"
/>

<DataTable data={totals} rows=all title="Totals over all months" wrapTitles=true>
    <Column id=actual_provider title="Processed by"/>
    <Column id=alternative_provider title="Alternative"/>
    <Column id=payments title="Payments" fmt=num0/>
    <Column id=volume_eur title="Volume (M01)" fmt=eur0/>
    <Column id=actual_expected_eur title="Own contract" fmt=eur2/>
    <Column id=alternative_expected_eur title="Alternative contract" fmt=eur2/>
    <Column id=saving_eur title="Saving" fmt=eur2/>
</DataTable>

<DataTable data={comparison} rows=all wrapTitles=true>
    <Column id=month title="Month"/>
    <Column id=actual_provider title="Processed by"/>
    <Column id=alternative_provider title="Alternative"/>
    <Column id=payments title="Payments" fmt=num0/>
    <Column id=volume_eur title="Volume (M01)" fmt=eur0/>
    <Column id=actual_billed_eur title="Billed" fmt=eur2/>
    <Column id=actual_expected_eur title="Own contract" fmt=eur2/>
    <Column id=alternative_expected_eur title="Alternative contract" fmt=eur2/>
    <Column id=saving_eur title="Saving" fmt=eur2/>
    <Column id=actual_rate_bps title="Own rate (bps)" fmt=num1/>
    <Column id=alternative_rate_bps title="Alternative rate (bps)" fmt=num1/>
</DataTable>
