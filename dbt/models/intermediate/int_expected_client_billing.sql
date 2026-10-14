-- What Fernway should bill each client under its pricing agreement (data contract sections 4.2 and 8.5): one row
-- per ledger event × invoice line component, plus client × month rows for the platform fee and the discounts.
-- Amounts are exact, in 10⁻⁸ minor units (`exact_scale`), so a percentage of a basis-point fee sum stays an
-- integer; the invoice line rounds the client × month × component sum once (`int_client_billing_comparison`).
-- Invoices are built from the ledger export by UTC month (A12), so every month is checked, the last one included
-- (A30).
with agreements as (
    select
        contract_version_id,
        counterparty as client_id,
        contract_id,
        contract_version,
        effective_from,
        effective_to,
        currency,
        rounding_mode,
        source_file as contract_file
    from {{ ref('stg_contracts__contract_versions') }}
    where party = 'client'
),

terms as (
    select a.*, t.clause, t.kind, t.parameters, t.amount_minor, t.bps, t.discount_pct, t.valid_until
    from {{ ref('stg_contracts__contract_terms') }} as t
    inner join agreements as a on a.contract_version_id = t.contract_version_id
),

events as (
    select *, cast(date_trunc('month', event_timestamp_utc) as date) as month
    from {{ ref('int_ledger_events') }}
    where (event_type = 'payment' and payment_status = 'succeeded') or event_type = 'payout'
),

-- Clause 2.1: amount × bps / 10000 + fixed by card segment, per succeeded payment, version at `created_at`.
payments as (
    select
        e.event_id,
        e.client_id,
        e.month,
        e.event_timestamp_utc,
        e.amount_minor,
        e.card_segment,
        t.contract_version_id,
        t.contract_id,
        t.contract_version,
        t.clause,
        t.currency,
        t.rounding_mode,
        t.contract_file,
        cast(json_extract_string(t.parameters, '$.segments.' || e.card_segment || '.bps') as integer) as bps,
        cast(json_extract_string(t.parameters, '$.segments.' || e.card_segment || '.fixed_minor') as bigint)
            as fixed_minor,
        e.source_file,
        e.source_row
    from events as e
    left join terms as t
        on t.client_id = e.client_id
        and t.kind = 'payment_fee_by_segment'
        and cast(e.event_timestamp_utc as date) >= t.effective_from
        and (t.effective_to is null or cast(e.event_timestamp_utc as date) <= t.effective_to)
    where e.event_type = 'payment'
),

payment_rows as (
    select
        'payment' as event_type,
        event_id,
        client_id,
        month,
        'payment_fees' as component,
        contract_id,
        contract_version,
        clause,
        currency,
        rounding_mode,
        (cast(amount_minor as hugeint) * bps + cast(fixed_minor as hugeint) * 10000) * ({{ exact_scale() }} // 10000)
            as exact_amount,
        amount_minor as basis_minor,
        bps as rate_bps,
        fixed_minor,
        cast(null as integer) as discount_pct,
        cast(null as integer) as tier_no,
        card_segment,
        event_timestamp_utc,
        source_file || ':' || source_row || '; ' || contract_file || ' §' || clause as evidence
    from payments
),

-- Payouts are dated by execution (A13): version, month and FX hour.
payouts as (
    select
        e.*,
        v.contract_id,
        v.contract_version,
        v.contract_version_id,
        v.currency as contract_currency,
        v.rounding_mode,
        v.contract_file,
        fx.mid
    from events as e
    left join agreements as v
        on v.client_id = e.client_id
        and cast(e.event_timestamp_utc as date) >= v.effective_from
        and (v.effective_to is null or cast(e.event_timestamp_utc as date) <= v.effective_to)
    left join {{ ref('stg_fx__mid_hourly') }} as fx
        on fx.pair = 'EUR' || e.currency
        and fx.hour_start_utc = date_trunc('hour', e.event_timestamp_utc)
    where e.event_type = 'payout'
),

-- Clause 2.2: a fixed fee per payout on its rail. A rail the version has no fee for leaves `fixed_minor` null,
-- which the not_null test on `exact_amount` reports.
payout_fee_rows as (
    select
        'payout' as event_type,
        p.event_id,
        p.client_id,
        p.month,
        'payout_fees_' || p.rail as component,
        p.contract_id,
        p.contract_version,
        t.clause,
        p.contract_currency as currency,
        p.rounding_mode,
        cast(json_extract_string(t.parameters, '$.rails.' || p.rail || '.fixed_minor') as hugeint) * {{ exact_scale() }}
            as exact_amount,
        cast(null as bigint) as basis_minor,
        cast(null as integer) as rate_bps,
        cast(json_extract_string(t.parameters, '$.rails.' || p.rail || '.fixed_minor') as bigint) as fixed_minor,
        cast(null as integer) as discount_pct,
        cast(null as integer) as tier_no,
        cast(null as varchar) as card_segment,
        p.event_timestamp_utc,
        p.source_file || ':' || p.source_row || '; ' || p.contract_file || ' §' || t.clause as evidence
    from payouts as p
    left join terms as t on t.contract_version_id = p.contract_version_id and t.kind = 'payout_fee_by_rail'
),

-- Clause 2.3: bps of E = round(amount / mid) per non-EUR payout, mid at the execution hour (A14).
fx_rows as (
    select
        'payout' as event_type,
        p.event_id,
        p.client_id,
        p.month,
        'fx_markup' as component,
        p.contract_id,
        p.contract_version,
        t.clause,
        p.contract_currency as currency,
        p.rounding_mode,
        cast({{ round_div('cast(p.amount_minor as hugeint) * 1000000', micros('p.mid'), 'p.rounding_mode') }}
            as hugeint) * t.bps * ({{ exact_scale() }} // 10000) as exact_amount,
        {{ round_div('cast(p.amount_minor as hugeint) * 1000000', micros('p.mid'), 'p.rounding_mode') }}
            as basis_minor,
        t.bps as rate_bps,
        cast(null as bigint) as fixed_minor,
        cast(null as integer) as discount_pct,
        cast(null as integer) as tier_no,
        cast(null as varchar) as card_segment,
        p.event_timestamp_utc,
        p.source_file || ':' || p.source_row || '; fx__mid_hourly EUR' || p.currency || ' '
            || strftime(date_trunc('hour', p.event_timestamp_utc), '%Y-%m-%dT%H:00Z') || '; ' || p.contract_file
            || ' §' || t.clause as evidence
    from payouts as p
    left join terms as t on t.contract_version_id = p.contract_version_id and t.kind = 'fx_markup'
    where p.currency <> 'EUR'
),

-- Every client × invoice month (UTC months with ledger payments or payouts), with the version in force on the
-- month's first day for the monthly terms.
client_months as (
    select
        c.client_id,
        m.month,
        v.contract_version_id,
        v.contract_id,
        v.contract_version,
        v.currency,
        v.rounding_mode,
        v.contract_file
    from {{ ref('stg_fernway__clients') }} as c
    cross join (select distinct month from events) as m
    left join agreements as v
        on v.client_id = c.client_id
        and m.month >= v.effective_from
        and (v.effective_to is null or m.month <= v.effective_to)
),

month_payments as (
    select
        cm.client_id,
        cm.month,
        coalesce(sum(p.amount_minor), 0) as volume_minor,
        count(p.event_id) as payments,
        coalesce(sum(pr.exact_amount), 0) as payment_fee_exact,
        coalesce(sum(pr.exact_amount) filter (where cast(p.event_timestamp_utc as date) <= promo.valid_until), 0)
            as promo_fee_exact
    from client_months as cm
    left join terms as promo on promo.contract_version_id = cm.contract_version_id and promo.kind = 'promo_discount'
    left join payments as p on p.client_id = cm.client_id and p.month = cm.month
    left join payment_rows as pr on pr.event_id = p.event_id
    group by all
),

-- Clause 3.1: the monthly platform fee.
platform_rows as (
    select
        'client_month' as event_type,
        cast(null as varchar) as event_id,
        cm.client_id,
        cm.month,
        'platform_fee' as component,
        cm.contract_id,
        cm.contract_version,
        t.clause,
        cm.currency,
        cm.rounding_mode,
        cast(t.amount_minor as hugeint) * {{ exact_scale() }} as exact_amount,
        cast(null as bigint) as basis_minor,
        cast(null as integer) as rate_bps,
        t.amount_minor as fixed_minor,
        cast(null as integer) as discount_pct,
        cast(null as integer) as tier_no,
        cast(null as varchar) as card_segment,
        cast(null as timestamp) as event_timestamp_utc,
        cm.contract_file || ' §' || t.clause as evidence
    from client_months as cm
    left join terms as t on t.contract_version_id = cm.contract_version_id and t.kind = 'platform_fee'
),

-- Clause 4.1 (retroactive): the tier of the month's processed volume sets the discount on all payment fees,
-- computed on the unrounded fee sum (A14).
volume_discount_rows as (
    select
        'client_month' as event_type,
        cast(null as varchar) as event_id,
        cm.client_id,
        cm.month,
        'volume_discount' as component,
        cm.contract_id,
        cm.contract_version,
        tr.clause,
        cm.currency,
        cm.rounding_mode,
        -mp.payment_fee_exact * tr.discount_pct // 100 as exact_amount,
        mp.volume_minor as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as bigint) as fixed_minor,
        tr.discount_pct,
        tr.tier_no,
        cast(null as varchar) as card_segment,
        cast(null as timestamp) as event_timestamp_utc,
        'ledger payments of ' || cm.client_id || ' in ' || strftime(cm.month, '%Y-%m') || ' (month volume); '
            || cm.contract_file || ' §' || tr.clause as evidence
    from client_months as cm
    inner join month_payments as mp on mp.client_id = cm.client_id and mp.month = cm.month
    left join {{ ref('int_contract_tiers') }} as tr
        on tr.contract_version_id = cm.contract_version_id
        and tr.kind = 'volume_discount_tiered'
        and mp.volume_minor >= tr.from_minor
        and (tr.up_to_minor is null or mp.volume_minor < tr.up_to_minor)
),

-- Clause 4.2: the promotion covers payments created on or before `valid_until` (UTC date, inclusive); a row for
-- every month of an agreement that has a promotion, zeros after the end date.
promo_rows as (
    select
        'client_month' as event_type,
        cast(null as varchar) as event_id,
        cm.client_id,
        cm.month,
        'promo_discount' as component,
        cm.contract_id,
        cm.contract_version,
        t.clause,
        cm.currency,
        cm.rounding_mode,
        -mp.promo_fee_exact * t.discount_pct // 100 as exact_amount,
        cast(null as bigint) as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as bigint) as fixed_minor,
        t.discount_pct,
        cast(null as integer) as tier_no,
        cast(null as varchar) as card_segment,
        cast(null as timestamp) as event_timestamp_utc,
        'ledger payments of ' || cm.client_id || ' in ' || strftime(cm.month, '%Y-%m') || ' created up to '
            || strftime(t.valid_until, '%Y-%m-%d') || '; ' || cm.contract_file || ' §' || t.clause as evidence
    from client_months as cm
    inner join month_payments as mp on mp.client_id = cm.client_id and mp.month = cm.month
    inner join terms as t on t.contract_version_id = cm.contract_version_id and t.kind = 'promo_discount'
),

expected as (
    select * from payment_rows
    union all by name
    select * from payout_fee_rows
    union all by name
    select * from fx_rows
    union all by name
    select * from platform_rows
    union all by name
    select * from volume_discount_rows
    union all by name
    select * from promo_rows
)

select
    coalesce(event_id, client_id || ':' || strftime(month, '%Y-%m')) || ':' || component as expected_billing_id,
    event_type,
    event_id,
    client_id,
    month,
    component,
    contract_id,
    contract_version,
    clause,
    currency,
    rounding_mode,
    cast(exact_amount as hugeint) as exact_amount,
    basis_minor,
    rate_bps,
    fixed_minor,
    discount_pct,
    tier_no,
    card_segment,
    event_timestamp_utc,
    evidence
from expected
