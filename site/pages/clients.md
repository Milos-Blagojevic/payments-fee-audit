---
title: Clients
sidebar_position: 7
---

Synthetic data; clients, prices and rates are illustrative. Fernway bills its merchant clients under pricing agreements. Each client invoice line (client × month × component) is checked against the agreement; a negative difference is revenue leakage (M09), billed too little, which Fernway corrects on its own invoices rather than disputes. The margin (M10) is what Fernway billed minus the provider costs of the client's events.

```sql leakage_totals
select
    sum(revenue_leakage_minor) / 100.0 as leakage_eur,
    sum(billed_minor) / 100.0 as billed_eur,
    sum(margin_minor) / 100.0 as margin_eur,
    sum(margin_minor) * 10000.0 / nullif(sum(volume_minor), 0) as margin_bps,
    count(distinct client_id) as clients
from fees.client_margin
```

```sql finding_totals
select count(*) as findings, count(distinct client_id) as clients_affected
from fees.client_findings
```

<BigValue data={leakage_totals} value=leakage_eur fmt=eur2 title="Revenue leakage (M09)"/>
<BigValue data={finding_totals} value=findings fmt=num0 title="Client billing findings"/>
<BigValue data={finding_totals} value=clients_affected fmt=num0 title="Clients affected"/>
<BigValue data={leakage_totals} value=billed_eur fmt=eur0 title="Billed to clients"/>
<BigValue data={leakage_totals} value=margin_eur fmt=eur0 title="Margin (M10)"/>
<BigValue data={leakage_totals} value=margin_bps fmt=num1 title="Margin, bps of volume"/>

## Leakage findings

```sql clients
select distinct client_id from fees.client_margin order by client_id
```

```sql leak_types
select distinct finding_type from fees.client_findings order by finding_type
```

```sql leak_months
select distinct month_label from fees.client_findings order by month_label
```

<Dropdown data={clients} name=client value=client_id title="Client" defaultValue="%">
    <DropdownOption value="%" valueLabel="All clients"/>
</Dropdown>

<Dropdown data={leak_types} name=leak_type value=finding_type title="Finding type" defaultValue="%">
    <DropdownOption value="%" valueLabel="All types"/>
</Dropdown>

<Dropdown data={leak_months} name=leak_month value=month_label title="Month" defaultValue="%">
    <DropdownOption value="%" valueLabel="All months"/>
</Dropdown>

```sql leak_filtered
select
    finding_id,
    client_id,
    finding_type,
    month_label as month,
    component,
    term,
    expected_minor / 100.0 as expected_eur,
    billed_minor / 100.0 as billed_eur,
    difference_minor / 100.0 as difference_eur,
    formula,
    evidence,
    invoice_id,
    method
from fees.client_findings
where client_id like '${inputs.client.value}'
  and finding_type like '${inputs.leak_type.value}'
  and month_label like '${inputs.leak_month.value}'
order by abs(difference_minor) desc, finding_id
```

```sql leak_by_type_month
select month, finding_type, count(*) as findings, sum(difference_eur) as difference_eur
from ${leak_filtered}
group by all
order by month, finding_type
```

```sql leak_by_client
select client_id, finding_type, count(*) as findings, sum(difference_eur) as difference_eur
from ${leak_filtered}
group by all
order by sum(difference_eur), client_id
```

<BarChart
    data={leak_by_type_month}
    x=month
    y=difference_eur
    series=finding_type
    sort=false
    yFmt=eur
    title="Billed − agreement by month and finding type (negative = billed too little)"
    emptySet=pass
    emptyMessage="No client findings for this selection."
/>

<DataTable data={leak_by_client} rows=10 title="By client and finding type" emptySet=pass emptyMessage="No client findings for this selection.">
    <Column id=client_id title="Client"/>
    <Column id=finding_type title="Finding type"/>
    <Column id=findings title="Findings" fmt=num0 totalAgg=sum/>
    <Column id=difference_eur title="Billed − agreement" fmt=eur2 totalAgg=sum/>
</DataTable>

<DataTable data={leak_filtered} rows=10 search=true wrapTitles=true downloadable=true emptySet=pass emptyMessage="No client findings for this selection.">
    <Column id=month title="Month"/>
    <Column id=client_id title="Client"/>
    <Column id=finding_type title="Type"/>
    <Column id=difference_eur title="Difference" fmt=eur2/>
    <Column id=formula title="Formula" wrap=true/>
    <Column id=evidence title="Evidence" wrap=true/>
</DataTable>

## Margin per client and month

Cost allocation (assumptions A09 and A32): provider fees are allocated to the client whose ledger event they belong to, by UTC month; a provider line without a ledger event goes to the client the provider reported. Monthly provider charges without an event are split by volume share in the provider's month: the monthly minimum by processed volume, the volume adjustment by EEA consumer card volume, in whole cents. The FX spread cost (M08) of the client's payouts is a cost too. Provider fees on lines after the ledger ends are billed to clients in the next cycle, so they are shown as pending and kept out of the month's margin.

```sql margin_by_month
select
    month_label as month,
    sum(billed_minor) / 100.0 as billed_eur,
    sum(provider_fees_minor) / 100.0 as provider_fees_eur,
    sum(fx_spread_cost_minor) / 100.0 as fx_spread_cost_eur,
    sum(margin_minor) / 100.0 as margin_eur,
    sum(revenue_leakage_minor) / 100.0 as leakage_eur
from fees.client_margin
group by all
order by month
```

```sql margin_long
select month, 'Provider fees' as part, provider_fees_eur as eur from ${margin_by_month}
union all
select month, 'FX spread cost (M08)' as part, fx_spread_cost_eur as eur from ${margin_by_month}
union all
select month, 'Margin (M10)' as part, margin_eur as eur from ${margin_by_month}
order by month
```

<BarChart
    data={margin_long}
    x=month
    y=eur
    series=part
    sort=false
    yFmt=eur0k
    title="Client billing split into provider costs and margin, all clients"
/>

```sql margin_rows
select
    client_id,
    month_label as month,
    volume_minor / 100.0 as volume_eur,
    billed_minor / 100.0 as billed_eur,
    expected_minor / 100.0 as expected_eur,
    revenue_leakage_minor / 100.0 as leakage_eur,
    event_provider_fees_minor / 100.0 as event_fees_eur,
    volume_share_provider_fees_minor / 100.0 as volume_share_fees_eur,
    fx_spread_cost_minor / 100.0 as fx_spread_cost_eur,
    margin_minor / 100.0 as margin_eur,
    margin_bps,
    pending_provider_fees_minor / 100.0 as pending_fees_eur
from fees.client_margin
where client_id like '${inputs.client.value}'
order by client_id, month
```

```sql margin_by_client
select
    client_id,
    sum(volume_eur) as volume_eur,
    sum(billed_eur) as billed_eur,
    sum(leakage_eur) as leakage_eur,
    sum(event_fees_eur + volume_share_fees_eur + fx_spread_cost_eur) as cost_eur,
    sum(margin_eur) as margin_eur,
    sum(margin_eur) * 10000.0 / nullif(sum(volume_eur), 0) as margin_bps
from ${margin_rows}
group by all
order by margin_bps
```

<DataTable data={margin_by_client} rows=10 search=true title="By client, all months" wrapTitles=true>
    <Column id=client_id title="Client"/>
    <Column id=volume_eur title="Volume" fmt=eur0/>
    <Column id=billed_eur title="Billed" fmt=eur2 totalAgg=sum/>
    <Column id=leakage_eur title="Leakage (M09)" fmt=eur2 totalAgg=sum/>
    <Column id=cost_eur title="Provider costs incl. FX spread" fmt=eur2 totalAgg=sum/>
    <Column id=margin_eur title="Margin (M10)" fmt=eur2 totalAgg=sum/>
    <Column id=margin_bps title="Margin (bps)" fmt=num1/>
</DataTable>

<DataTable data={margin_rows} rows=12 search=true downloadable=true title="By client and month" wrapTitles=true>
    <Column id=client_id title="Client"/>
    <Column id=month title="Month"/>
    <Column id=volume_eur title="Volume" fmt=eur0/>
    <Column id=billed_eur title="Billed" fmt=eur2/>
    <Column id=expected_eur title="Agreement" fmt=eur2/>
    <Column id=leakage_eur title="Leakage (M09)" fmt=eur2/>
    <Column id=event_fees_eur title="Event provider fees" fmt=eur2/>
    <Column id=volume_share_fees_eur title="Volume-share fees" fmt=eur2/>
    <Column id=fx_spread_cost_eur title="FX spread cost" fmt=eur2/>
    <Column id=margin_eur title="Margin (M10)" fmt=eur2/>
    <Column id=margin_bps title="Margin (bps)" fmt=num1/>
    <Column id=pending_fees_eur title="Pending fees" fmt=eur2/>
</DataTable>
