---
title: Findings
sidebar_position: 2
---

Synthetic data; contract rates are illustrative. Provider fee findings come from two methods. A **rule** finding is one charge (or one provider × month for month-level terms) where the billed amount differs from the contract by at least one cent; the formula shows the expected calculation with the clause used. An **anomaly** finding is billed money no rule and no contract term explains, found by the [anomaly model](/anomalies); its formula states the baseline, the observed value and the threshold. The evidence lists the source files and rows. Overcharge, undercharge and the dispute queue count rule findings only. Client billing findings are on the [Clients](/clients) page.

```sql providers
select distinct provider from fees.findings order by provider
```

```sql finding_types
select distinct finding_type from fees.findings order by finding_type
```

```sql months
select distinct month_label from fees.findings order by month_label
```

```sql methods
select distinct method from fees.findings order by method desc
```

<Dropdown data={methods} name=method value=method title="Method" defaultValue="%">
    <DropdownOption value="%" valueLabel="Rule and anomaly"/>
</Dropdown>

<Dropdown data={providers} name=provider value=provider title="Provider" defaultValue="%">
    <DropdownOption value="%" valueLabel="All providers"/>
</Dropdown>

<Dropdown data={finding_types} name=finding_type value=finding_type title="Finding type" defaultValue="%">
    <DropdownOption value="%" valueLabel="All types"/>
</Dropdown>

<Dropdown data={months} name=month value=month_label title="Month" defaultValue="%">
    <DropdownOption value="%" valueLabel="All months"/>
</Dropdown>

```sql filtered
select
    finding_id,
    method,
    provider,
    finding_type,
    month_label as month,
    component,
    term,
    expected_minor / 100.0 as expected_eur,
    billed_minor / 100.0 as billed_eur,
    difference_minor / 100.0 as difference_eur,
    direction,
    formula,
    evidence,
    invoice_id,
    dispute_deadline,
    days_left
from fees.findings
where provider like '${inputs.provider.value}'
  and finding_type like '${inputs.finding_type.value}'
  and month_label like '${inputs.month.value}'
  and method like '${inputs.method.value}'
order by abs(difference_minor) desc, finding_id
```

```sql filtered_summary
select
    count(*) filter (where method = 'rule') as rule_findings,
    count(*) filter (where method = 'anomaly') as anomaly_findings,
    coalesce(sum(difference_eur) filter (where method = 'rule' and finding_type <> 'rounding' and difference_eur > 0), 0) as overcharge_eur,
    coalesce(sum(difference_eur) filter (where method = 'rule' and finding_type <> 'rounding' and difference_eur < 0), 0) as undercharge_eur,
    coalesce(sum(difference_eur) filter (where method = 'rule' and finding_type = 'rounding'), 0) as rounding_eur,
    coalesce(sum(difference_eur) filter (where method = 'anomaly'), 0) as anomaly_eur
from ${filtered}
```

<BigValue data={filtered_summary} value=rule_findings fmt=num0 title="Rule findings"/>
<BigValue data={filtered_summary} value=overcharge_eur fmt=eur2 title="Rule overcharge"/>
<BigValue data={filtered_summary} value=undercharge_eur fmt=eur2 title="Rule undercharge"/>
<BigValue data={filtered_summary} value=rounding_eur fmt=eur2 title="Rounding"/>
<BigValue data={filtered_summary} value=anomaly_findings fmt=num0 title="Anomaly findings"/>
<BigValue data={filtered_summary} value=anomaly_eur fmt=eur2 title="Anomaly amount"/>

```sql filtered_by_type
select method, finding_type, direction, count(*) as findings, sum(difference_eur) as difference_eur
from ${filtered}
group by all
order by method desc, abs(sum(difference_eur)) desc
```

<DataTable data={filtered_by_type} rows=all title="By method and finding type">
    <Column id=method title="Method"/>
    <Column id=finding_type title="Finding type"/>
    <Column id=direction title="Direction"/>
    <Column id=findings title="Findings" fmt=num0 totalAgg=sum/>
    <Column id=difference_eur title="Billed − contract" fmt=eur2 totalAgg=sum/>
</DataTable>

## Findings

Sorted by the size of the difference. Use the search box for a type, provider or source file.

<DataTable data={filtered} rows=15 search=true wrapTitles=true downloadable=true>
    <Column id=month title="Month"/>
    <Column id=method title="Method"/>
    <Column id=provider title="Provider"/>
    <Column id=finding_type title="Type"/>
    <Column id=difference_eur title="Difference" fmt=eur2/>
    <Column id=formula title="Formula" wrap=true/>
    <Column id=evidence title="Evidence" wrap=true/>
</DataTable>

The same findings with their contract term, amounts, invoice and dispute deadline:

<DataTable data={filtered} rows=15 search=true wrapTitles=true>
    <Column id=finding_id title="Finding id"/>
    <Column id=month title="Month"/>
    <Column id=provider title="Provider"/>
    <Column id=component title="Component"/>
    <Column id=term title="Contract term"/>
    <Column id=expected_eur title="Contract" fmt=eur2/>
    <Column id=billed_eur title="Billed" fmt=eur2/>
    <Column id=difference_eur title="Difference" fmt=eur2/>
    <Column id=invoice_id title="Invoice"/>
    <Column id=dispute_deadline title="Dispute deadline"/>
</DataTable>

## Contract terms

```sql terms
select
    contract,
    counterparty as provider,
    clause,
    title,
    clause_text,
    effective_from,
    effective_to,
    dispute_window_days
from fees.contract_terms
where counterparty like '${inputs.provider.value}'
order by contract_id, contract_version, clause
```

<DataTable data={terms} rows=10 search=true wrapTitles=true>
    <Column id=contract title="Contract"/>
    <Column id=clause title="Clause"/>
    <Column id=title title="Title"/>
    <Column id=clause_text title="Term" wrap=true/>
    <Column id=effective_from title="From"/>
    <Column id=effective_to title="To"/>
    <Column id=dispute_window_days title="Dispute window (days)"/>
</DataTable>
