---
title: Overview
sidebar_position: 1
---

Fernway is a fictional payments company. Every number on this site comes from synthetic, seeded data with planted billing errors; contract rates are illustrative. Amounts are in EUR.

This page summarises the provider fee findings: charges whose billed amount differs from the contract. Metric ids (M01–M08) refer to `METRICS.md`.

```sql totals
select
    sum(overcharge_minor) / 100.0 as overcharge_eur,
    sum(undercharge_minor) / 100.0 as undercharge_eur,
    sum(recoverable_minor) / 100.0 as recoverable_eur,
    sum(overcharge_minor - recoverable_minor) / 100.0 as expired_eur,
    sum(overcharge_findings) as overcharge_findings,
    sum(undercharge_findings) as undercharge_findings,
    sum(open_findings) as open_findings,
    count(*) as invoices
from fees.dispute_queue
```

```sql reference_date
select strftime(min(earliest_deadline - to_days(days_left::integer)), '%Y-%m-%d') as as_of_date
from fees.dispute_queue
```

<BigValue data={totals} value=overcharge_eur fmt=eur2 title="Overcharge (M05)"/>
<BigValue data={totals} value=undercharge_eur fmt=eur2 title="Undercharge (M06)"/>
<BigValue data={totals} value=recoverable_eur fmt=eur2 title="Recoverable (M07)"/>
<BigValue data={totals} value=expired_eur fmt=eur2 title="Past the dispute deadline"/>

Overcharges are disputed with the provider; undercharges are reported but not disputed. An overcharge is recoverable while its dispute deadline is on or after the reference date <Value data={reference_date} column=as_of_date/>. Rounding differences are excluded from these totals.

## Money found by finding type

```sql by_type
select
    finding_type,
    direction,
    count(*) as findings,
    sum(difference_minor) / 100.0 as difference_eur
from fees.findings
group by all
order by abs(sum(difference_minor)) desc
```

<BarChart
    data={by_type}
    x=finding_type
    y=difference_eur
    series=direction
    swapXY=true
    yFmt=eur
    sort=false
    title="Billed minus contract, by finding type"
/>

<DataTable data={by_type} rows=all>
    <Column id=finding_type title="Finding type"/>
    <Column id=direction title="Direction"/>
    <Column id=findings title="Findings" fmt=num0/>
    <Column id=difference_eur title="Billed − contract" fmt=eur2 totalAgg=sum/>
</DataTable>

## Overcharge by provider and month

```sql by_provider_month
select
    provider,
    month_label as statement_month,
    sum(overcharge_minor) / 100.0 as overcharge_eur,
    sum(undercharge_minor) / 100.0 as undercharge_eur,
    sum(recoverable_minor) / 100.0 as recoverable_eur,
    sum(overcharge_minor - recoverable_minor) / 100.0 as expired_eur
from fees.dispute_queue
group by all
order by statement_month, provider
```

<BarChart
    data={by_provider_month}
    x=statement_month
    sort=false
    y=overcharge_eur
    series=provider
    yFmt=eur
    title="Overcharge (M05) by statement month"
/>

```sql recoverable_split
select statement_month, 'Recoverable' as status, sum(recoverable_eur) as eur
from ${by_provider_month} group by all
union all
select statement_month, 'Past the deadline' as status, sum(expired_eur) as eur
from ${by_provider_month} group by all
order by statement_month
```

<BarChart
    data={recoverable_split}
    x=statement_month
    sort=false
    y=eur
    series=status
    yFmt=eur
    title="Overcharge recoverable (M07) or past the deadline"
/>

## Metrics on this site

| Id | Metric | Page |
|---|---|---|
| M01 | Processed volume | [Provider costs](/provider-costs) |
| M02 | Provider fees | [Provider costs](/provider-costs) |
| M03 | Effective rate | [Provider costs](/provider-costs) |
| M04 | Markup rate | [Provider costs](/provider-costs) |
| M05 | Overcharge | this page, [Dispute queue](/dispute-queue) |
| M06 | Undercharge | this page, [Dispute queue](/dispute-queue) |
| M07 | Recoverable | this page, [Dispute queue](/dispute-queue) |
| M08 | FX spread cost | [FX conversions](/fx-conversions) |
