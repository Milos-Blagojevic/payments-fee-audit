---
title: FX conversions
sidebar_position: 6
---

Synthetic data; contract rates and FX rates are illustrative. Non-EUR payouts are converted by the payout provider, which debits EUR. The spread is the gap between the mid rate of the execution hour and the rate applied; its cost (M08) is the EUR debited minus the EUR equivalent at mid. The contract caps the spread per currency; the part of the debit above the cap is a finding, as is a rate taken from a different hour than the execution.

```sql totals
select
    sum(conversions) as conversions,
    sum(spread_cost_minor) / 100.0 as spread_cost_eur,
    sum(over_cap_cost_minor) / 100.0 as over_cap_cost_eur,
    sum(spread_above_cap_findings) as spread_above_cap_findings,
    sum(wrong_hour_findings) as wrong_hour_findings
from fees.fx_monthly
```

<BigValue data={totals} value=conversions fmt=num0 title="Conversions"/>
<BigValue data={totals} value=spread_cost_eur fmt=eur2 title="Spread cost (M08)"/>
<BigValue data={totals} value=over_cap_cost_eur fmt=eur2 title="Cost above the cap"/>
<BigValue data={totals} value=spread_above_cap_findings fmt=num0 title="Spread above cap findings"/>
<BigValue data={totals} value=wrong_hour_findings fmt=num0 title="Wrong rate hour findings"/>

## Spread against the cap

Each bar counts conversions by how far the realised spread sits from the currency's cap, in whole basis points (−1 = up to one basis point below the cap, 0 = from the cap to one basis point above it). The second chart shows where the cost above the cap sits.

```sql currencies
select distinct currency from fees.fx_spread_distribution order by currency
```

<Dropdown data={currencies} name=currency value=currency title="Currency" defaultValue="%">
    <DropdownOption value="%" valueLabel="All currencies"/>
</Dropdown>

```sql distribution
select bps_vs_cap, currency, sum(conversions) as conversions, sum(over_cap_cost_minor) / 100.0 as over_cap_cost_eur
from fees.fx_spread_distribution
where currency like '${inputs.currency.value}'
group by all
order by bps_vs_cap, currency
```

<BarChart
    data={distribution}
    x=bps_vs_cap
    sort=false
    y=conversions
    series=currency
    xAxisTitle="spread − cap (bps)"
    xType=category
    yFmt=num0
    title="Conversions by spread relative to the cap"
/>

<BarChart
    data={distribution}
    x=bps_vs_cap
    sort=false
    y=over_cap_cost_eur
    series=currency
    xAxisTitle="spread − cap (bps)"
    xType=category
    yFmt=eur
    title="Cost above the cap by spread relative to the cap"
/>

## By month

```sql monthly
select
    month_label as month,
    currency,
    cap_bps,
    conversions,
    compared,
    eur_at_mid_minor / 100.0 as eur_at_mid_eur,
    spread_cost_minor / 100.0 as spread_cost_eur,
    over_cap_cost_minor / 100.0 as over_cap_cost_eur,
    spread_above_cap_findings,
    wrong_hour_findings
from fees.fx_monthly
where currency like '${inputs.currency.value}'
order by month, currency
```

<BarChart
    data={monthly}
    x=month
    sort=false
    y=spread_cost_eur
    series=currency
    yFmt=eur
    title="Spread cost (M08) by month"
/>

<BarChart
    data={monthly}
    x=month
    sort=false
    y=over_cap_cost_eur
    series=currency
    yFmt=eur
    title="Cost above the cap by month"
/>

<DataTable data={monthly} rows=all wrapTitles=true>
    <Column id=month title="Month"/>
    <Column id=currency title="Currency"/>
    <Column id=cap_bps title="Cap (bps)" fmt=num0/>
    <Column id=conversions title="Conversions" fmt=num0 totalAgg=sum/>
    <Column id=compared title="Compared" fmt=num0 totalAgg=sum/>
    <Column id=eur_at_mid_eur title="EUR at mid" fmt=eur0 totalAgg=sum/>
    <Column id=spread_cost_eur title="Spread cost (M08)" fmt=eur2 totalAgg=sum/>
    <Column id=over_cap_cost_eur title="Above the cap" fmt=eur2 totalAgg=sum/>
    <Column id=spread_above_cap_findings title="Spread findings" fmt=num0 totalAgg=sum/>
    <Column id=wrong_hour_findings title="Rate hour findings" fmt=num0 totalAgg=sum/>
</DataTable>

## Conversions with a finding

```sql fx_findings
select
    executed_at_utc,
    payout_id,
    currency,
    rail,
    amount_minor / 100.0 as amount,
    mid_rate,
    applied_rate,
    rate_timestamp_utc,
    rate_hour_matches,
    spread_bps,
    cap_bps,
    spread_cost_minor / 100.0 as spread_cost_eur,
    over_cap_cost_minor / 100.0 as over_cap_cost_eur,
    finding_type,
    term
from fees.fx_findings
where currency like '${inputs.currency.value}'
order by executed_at_utc
```

<DataTable data={fx_findings} rows=15 search=true wrapTitles=true downloadable=true>
    <Column id=executed_at_utc title="Executed (UTC)"/>
    <Column id=payout_id title="Payout"/>
    <Column id=currency title="Currency"/>
    <Column id=rail title="Rail"/>
    <Column id=amount title="Amount (payout currency)" fmt=num2/>
    <Column id=mid_rate title="Mid" fmt=num4/>
    <Column id=applied_rate title="Applied" fmt=num4/>
    <Column id=rate_timestamp_utc title="Rate hour (UTC)"/>
    <Column id=spread_bps title="Spread (bps)" fmt=num2/>
    <Column id=cap_bps title="Cap (bps)" fmt=num0/>
    <Column id=spread_cost_eur title="Spread cost" fmt=eur2/>
    <Column id=over_cap_cost_eur title="Above the cap" fmt=eur2/>
    <Column id=finding_type title="Finding type"/>
    <Column id=term title="Contract term"/>
</DataTable>
