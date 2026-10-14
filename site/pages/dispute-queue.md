---
title: Dispute queue
sidebar_position: 3
---

Synthetic data; contract rates are illustrative. One row per provider invoice with findings. The dispute deadline is the invoice date plus the contract's dispute window; days left count from the reference date <Value data={reference_date} column=as_of_date/>, not from today. Rounding differences are excluded.

```sql reference_date
select strftime(min(earliest_deadline - to_days(days_left::integer)), '%Y-%m-%d') as as_of_date
from fees.dispute_queue
```

```sql queue
select
    invoice_id,
    provider,
    month_label as statement_month,
    invoice_date,
    earliest_deadline,
    days_left,
    status,
    overcharge_findings,
    overcharge_minor / 100.0 as overcharge_eur,
    open_findings,
    recoverable_minor / 100.0 as recoverable_eur,
    undercharge_findings,
    undercharge_minor / 100.0 as undercharge_eur,
    finding_types
from fees.dispute_queue
order by status desc, days_left, invoice_id
```

```sql queue_totals
select
    count(*) filter (where status = 'open') as open_invoices,
    count(*) filter (where status = 'expired') as expired_invoices,
    sum(recoverable_eur) as recoverable_eur,
    min(days_left) filter (where status = 'open') as next_deadline_days
from ${queue}
```

<BigValue data={queue_totals} value=open_invoices fmt=num0 title="Invoices still open"/>
<BigValue data={queue_totals} value=expired_invoices fmt=num0 title="Invoices past the deadline"/>
<BigValue data={queue_totals} value=recoverable_eur fmt=eur2 title="Recoverable (M07)"/>
<BigValue data={queue_totals} value=next_deadline_days fmt=num0 title="Days to the next deadline"/>

<DataTable data={queue} rows=all wrapTitles=true downloadable=true>
    <Column id=invoice_id title="Invoice"/>
    <Column id=provider title="Provider"/>
    <Column id=statement_month title="Statement month"/>
    <Column id=invoice_date title="Invoice date"/>
    <Column id=earliest_deadline title="Earliest deadline"/>
    <Column id=days_left title="Days left"/>
    <Column id=status title="Status"/>
    <Column id=overcharge_findings title="Overcharge findings" fmt=num0 totalAgg=sum/>
    <Column id=overcharge_eur title="Overcharge (M05)" fmt=eur2 totalAgg=sum/>
    <Column id=open_findings title="Open findings" fmt=num0 totalAgg=sum/>
    <Column id=recoverable_eur title="Recoverable (M07)" fmt=eur2 totalAgg=sum/>
    <Column id=undercharge_findings title="Undercharge findings" fmt=num0 totalAgg=sum/>
    <Column id=undercharge_eur title="Undercharge (M06)" fmt=eur2 totalAgg=sum/>
    <Column id=finding_types title="Finding types" wrap=true/>
</DataTable>

## Invoice totals

Each provider statement month: the invoice total against the sum of its lines, and the billed lines against what the contract allows for the same charges. Billed amounts that cannot be checked yet (lines after the ledger ends) are shown as pending.

```sql reconciliation
select
    provider,
    month_label as statement_month,
    invoice_id,
    line_count,
    invoice_total_minor / 100.0 as invoice_total_eur,
    lines_total_minor / 100.0 as lines_total_eur,
    invoice_difference_minor / 100.0 as invoice_difference_eur,
    expected_total_minor / 100.0 as expected_total_eur,
    pending_billed_minor / 100.0 as pending_billed_eur,
    billed_minus_expected_minor / 100.0 as billed_minus_expected_eur,
    findings,
    findings_total_minor / 100.0 as findings_total_eur,
    rounding_total_minor / 100.0 as rounding_total_eur
from fees.invoice_reconciliation
order by provider, statement_month
```

<DataTable data={reconciliation} rows=all wrapTitles=true>
    <Column id=provider title="Provider"/>
    <Column id=statement_month title="Statement month"/>
    <Column id=invoice_id title="Invoice"/>
    <Column id=line_count title="Lines" fmt=num0/>
    <Column id=invoice_total_eur title="Invoice total" fmt=eur2/>
    <Column id=lines_total_eur title="Sum of lines" fmt=eur2/>
    <Column id=invoice_difference_eur title="Invoice − lines" fmt=eur2/>
    <Column id=expected_total_eur title="Contract" fmt=eur2/>
    <Column id=pending_billed_eur title="Pending" fmt=eur2/>
    <Column id=billed_minus_expected_eur title="Billed − contract" fmt=eur2 totalAgg=sum/>
    <Column id=findings title="Findings" fmt=num0 totalAgg=sum/>
    <Column id=findings_total_eur title="Findings total" fmt=eur2 totalAgg=sum/>
    <Column id=rounding_total_eur title="Rounding" fmt=eur2 totalAgg=sum/>
</DataTable>
