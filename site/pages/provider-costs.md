---
title: Provider costs
sidebar_position: 4
---

Synthetic data; contract rates are illustrative. Fees billed by each provider per UTC month, fee component and card segment, against the processed card volume (M01). Billed fees (M02) are net of credits; FX conversion debits are not fees and appear under [FX conversions](/fx-conversions).

```sql providers
select distinct provider from fees.provider_costs order by provider
```

<Dropdown data={providers} name=provider value=provider title="Provider" defaultValue="northgate"/>

```sql segments
select distinct card_segment from fees.provider_costs
where provider = '${inputs.provider.value}'
order by card_segment
```

<Dropdown data={segments} name=segment value=card_segment title="Card segment"/>

Card segment `not_applicable` holds payouts and monthly lines; `unknown` holds lines with no ledger event yet. Their rates are measured against the provider's whole volume.

## Processed volume (M01)

```sql volume
select
    month_label as month,
    card_segment,
    max(volume_minor) / 100.0 as volume_eur
from fees.provider_costs
where provider = '${inputs.provider.value}'
  and card_segment in ('eea_consumer', 'other')
group by all
order by month, card_segment
```

<BarChart
    data={volume}
    x=month
    sort=false
    y=volume_eur
    series=card_segment
    yFmt=eur0m
    title="Succeeded card payments by card segment"
    emptySet=pass
    emptyMessage="No card volume for this provider."
/>

## Effective rate by component (M03)

```sql rates
select
    month_label as month,
    component,
    effective_rate_bps,
    billed_minor / 100.0 as billed_eur
from fees.provider_costs
where provider = '${inputs.provider.value}'
  and card_segment = '${inputs.segment.value}'
order by month, component
```

<BarChart
    data={rates}
    x=month
    sort=false
    y=effective_rate_bps
    series=component
    yFmt=num1
    yAxisTitle="basis points"
    title="Billed fees ÷ volume, stacked by component"
    emptySet=pass
    emptyMessage="No fees for this provider and card segment; choose another card segment."
/>

## Markup rate (M04)

The acquirer markup as a share of volume, for the interchange++ provider.

```sql markup
select
    month_label as month,
    card_segment,
    effective_rate_bps as markup_rate_bps
from fees.provider_costs
where component = 'markup'
  and card_segment in ('eea_consumer', 'other')
order by month, card_segment
```

<LineChart
    data={markup}
    x=month
    y=markup_rate_bps
    series=card_segment
    yFmt=num1
    yAxisTitle="basis points"
    markers=true
    title="Markup rate by card segment"
/>

## Billed against contract (M02)

```sql billed_vs_expected
select
    month_label as month,
    component,
    lines,
    billed_minor / 100.0 as billed_eur,
    pending_billed_minor / 100.0 as pending_eur,
    expected_minor / 100.0 as expected_eur,
    difference_minor / 100.0 as difference_eur
from fees.provider_costs
where provider = '${inputs.provider.value}'
  and card_segment = '${inputs.segment.value}'
order by month, component
```

<DataTable data={billed_vs_expected} rows=all groupBy=month subtotals=true wrapTitles=true emptySet=pass emptyMessage="No fees for this provider and card segment; choose another card segment.">
    <Column id=month title="Month"/>
    <Column id=component title="Component"/>
    <Column id=lines title="Lines" fmt=num0 totalAgg=sum/>
    <Column id=billed_eur title="Billed (M02)" fmt=eur2 totalAgg=sum/>
    <Column id=pending_eur title="Pending" fmt=eur2 totalAgg=sum/>
    <Column id=expected_eur title="Contract" fmt=eur2 totalAgg=sum/>
    <Column id=difference_eur title="Billed − contract" fmt=eur2 totalAgg=sum/>
</DataTable>
