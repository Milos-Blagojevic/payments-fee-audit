-- What each ledger event should cost under the provider contract version in force at the event time
-- (data contract section 4.1): one row per ledger event × fee component, plus provider × month rows for monthly
-- minimums and volume adjustments. Integer money, rounding as the contract states, a formula with real numbers.
with events as (
    select
        e.*,
        v.contract_version_id,
        v.contract_id,
        v.contract_version,
        v.rounding_mode,
        v.other_rounding_mode,
        v.currency as contract_currency,
        v.source_file as contract_file
    from {{ ref('int_ledger_events') }} as e
    inner join {{ ref('int_provider_contract_versions') }} as v
        on v.provider = e.provider
        and e.provider_local_date >= v.effective_from
        and (v.effective_to is null or e.provider_local_date <= v.effective_to)
),

terms as (
    select * from {{ ref('stg_contracts__contract_terms') }}
),

tiers as (
    select * from {{ ref('int_contract_tiers') }}
),

months as (
    select m.*, v.source_file as contract_file
    from {{ ref('int_provider_months') }} as m
    left join {{ ref('int_provider_contract_versions') }} as v on v.contract_version_id = m.contract_version_id
),

payments as (
    select * from events where event_type = 'payment'
),

succeeded_payments as (
    select * from payments where payment_status = 'succeeded'
),

-- Clause 3.1 (pass_through): interchange and scheme fee from the versioned reference table.
pass_through as (
    select
        p.*,
        t.clause,
        i.reference,
        i.interchange_bps,
        i.scheme_fee_bps,
        i.scheme_fee_fixed_minor
    from succeeded_payments as p
    inner join terms as t on t.contract_version_id = p.contract_version_id and t.kind = 'pass_through'
    left join {{ ref('interchange_table_v1') }} as i
        on i.reference = t.reference
        and i.card_scheme = p.card_scheme
        and i.card_type = p.card_type
        and i.card_region = p.card_region
),

interchange_rows as (
    select
        'payment' as event_type, event_id, provider, provider_month as month, 'interchange' as component,
        contract_id, contract_version, clause, contract_currency,
        {{ bps_of('amount_minor', 'interchange_bps', 'rounding_mode') }} as expected_minor,
        {{ bps_of('amount_minor', 'interchange_bps', 'other_rounding_mode') }} as other_rounding_minor,
        amount_minor as basis_minor,
        interchange_bps as rate_bps,
        cast(null as integer) as tier_no,
        {{ fmt_money('amount_minor') }} || ' × ' || {{ fmt_bps('interchange_bps') }} || ' = '
            || {{ fmt_money(bps_of('amount_minor', 'interchange_bps', 'rounding_mode')) }} || ' ' || contract_currency
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || '; ' || reference || ' '
            || card_scheme || '/' || card_type || '/' || card_region || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from pass_through
),

scheme_fee_rows as (
    select
        'payment' as event_type, event_id, provider, provider_month as month, 'scheme_fee' as component,
        contract_id, contract_version, clause, contract_currency,
        {{ bps_of('amount_minor', 'scheme_fee_bps', 'rounding_mode') }} + scheme_fee_fixed_minor as expected_minor,
        {{ bps_of('amount_minor', 'scheme_fee_bps', 'other_rounding_mode') }} + scheme_fee_fixed_minor
            as other_rounding_minor,
        amount_minor as basis_minor,
        scheme_fee_bps as rate_bps,
        cast(null as integer) as tier_no,
        {{ fmt_money('amount_minor') }} || ' × ' || {{ fmt_bps('scheme_fee_bps') }} || ' + '
            || {{ fmt_money('scheme_fee_fixed_minor') }} || ' = '
            || {{ fmt_money(bps_of('amount_minor', 'scheme_fee_bps', 'rounding_mode') ~ ' + scheme_fee_fixed_minor') }}
            || ' ' || contract_currency
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || '; ' || reference || ' '
            || card_scheme || '/' || card_type || '/' || card_region || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from pass_through
),

-- Clause 4.2 (markup_bps_tiered, retroactive): the tier of the month's whole processed volume applies to every
-- payment of the month.
markup as (
    select
        p.*,
        t.clause,
        r.tier_no,
        r.bps,
        r.up_to_minor,
        m.volume_minor as month_volume_minor
    from succeeded_payments as p
    inner join terms as t
        on t.contract_version_id = p.contract_version_id and t.kind = 'markup_bps_tiered' and t.tiering = 'retroactive'
    inner join months as m on m.provider = p.provider and m.provider_month = p.provider_month
    inner join tiers as r
        on r.contract_term_id = t.contract_term_id
        and m.volume_minor >= r.from_minor
        and (r.up_to_minor is null or m.volume_minor < r.up_to_minor)
),

markup_rows as (
    select
        'payment' as event_type, event_id, provider, provider_month as month, 'markup' as component,
        contract_id, contract_version, clause, contract_currency,
        {{ bps_of('amount_minor', 'bps', 'rounding_mode') }} as expected_minor,
        {{ bps_of('amount_minor', 'bps', 'other_rounding_mode') }} as other_rounding_minor,
        amount_minor as basis_minor,
        bps as rate_bps,
        tier_no,
        {{ fmt_money('amount_minor') }} || ' × ' || {{ fmt_bps('bps') }} || ' = '
            || {{ fmt_money(bps_of('amount_minor', 'bps', 'rounding_mode')) }} || ' ' || contract_currency
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || '; tier ' || tier_no
            || ', month volume ' || {{ fmt_money('month_volume_minor') }} || ' ' || contract_currency
            || case when up_to_minor is null then '' else ' < ' || {{ fmt_money('up_to_minor') }} end || ')'
            as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from markup
),

-- Clause 4.3 (per_transaction_fixed).
fixed_fee_rows as (
    select
        'payment' as event_type, p.event_id, p.provider, p.provider_month as month, 'fixed_fee' as component,
        p.contract_id, p.contract_version, t.clause, p.contract_currency,
        t.amount_minor as expected_minor,
        t.amount_minor as other_rounding_minor,
        p.amount_minor as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        {{ fmt_money('t.amount_minor') }} || ' per successful payment = ' || {{ fmt_money('t.amount_minor') }} || ' '
            || p.contract_currency || ' (' || {{ fmt_clause('p.contract_id', 'p.contract_version', 't.clause') }} || ')'
            as formula,
        p.event_timestamp_utc, p.card_segment, p.contract_file, p.source_file, p.source_row
    from succeeded_payments as p
    inner join terms as t on t.contract_version_id = p.contract_version_id and t.kind = 'per_transaction_fixed'
),

-- Clause 3.1 (blended_rate): all-in fee by card segment on succeeded payments; no fee on declined or failed
-- attempts.
blended as (
    select
        p.*,
        t.clause,
        json_extract_string(t.parameters, '$.failed_attempts') as failed_attempts,
        cast(json_extract_string(t.parameters, '$.segments.' || p.card_segment || '.bps') as integer) as bps,
        cast(json_extract_string(t.parameters, '$.segments.' || p.card_segment || '.fixed_minor') as bigint)
            as fixed_minor
    from payments as p
    inner join terms as t on t.contract_version_id = p.contract_version_id and t.kind = 'blended_rate'
),

transaction_fee_rows as (
    select
        'payment' as event_type, event_id, provider, provider_month as month, 'transaction_fee' as component,
        contract_id, contract_version, clause, contract_currency,
        case
            when payment_status = 'succeeded' then {{ bps_of('amount_minor', 'bps', 'rounding_mode') }} + fixed_minor
            when failed_attempts = 'no_fee' then 0
            else cast(error('unsupported failed_attempts: ' || coalesce(failed_attempts, 'null')) as bigint)
        end as expected_minor,
        case
            when payment_status = 'succeeded'
                then {{ bps_of('amount_minor', 'bps', 'other_rounding_mode') }} + fixed_minor
            else 0
        end as other_rounding_minor,
        amount_minor as basis_minor,
        bps as rate_bps,
        cast(null as integer) as tier_no,
        case
            when payment_status = 'succeeded'
                then {{ fmt_money('amount_minor') }} || ' × ' || {{ fmt_bps('bps') }} || ' + '
                    || {{ fmt_money('fixed_minor') }} || ' = '
                    || {{ fmt_money(bps_of('amount_minor', 'bps', 'rounding_mode') ~ ' + fixed_minor') }}
                    || ' ' || contract_currency
            else 'no fee on a ' || payment_status || ' attempt = 0.00 ' || contract_currency
        end
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || '; segment ' || card_segment
            || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from blended
),

-- Expected markup of every payment, for the refund markup credit.
payment_markup as (
    select
        event_id as payment_id,
        expected_minor as markup_minor,
        other_rounding_minor as other_markup_minor,
        formula as markup_formula
    from markup_rows
),

-- Clause 5.1 / 5.2 (refund): the refund fee, and minus the original payment's expected markup when the
-- contract credits it.
refunds as (
    select
        r.*,
        t.clause,
        t.fee_minor,
        t.credit_original_markup,
        coalesce(pm.markup_minor, 0) as original_markup_minor,
        coalesce(pm.other_markup_minor, 0) as other_original_markup_minor,
        coalesce(pm.markup_formula, 'no markup on ' || r.original_payment_id) as original_markup_formula
    from events as r
    inner join terms as t on t.contract_version_id = r.contract_version_id and t.kind = 'refund'
    left join payment_markup as pm on pm.payment_id = r.original_payment_id
    where r.event_type = 'refund'
),

refund_fee_rows as (
    select
        'refund' as event_type, event_id, provider, provider_month as month, 'refund_fee' as component,
        contract_id, contract_version, clause, contract_currency,
        fee_minor as expected_minor,
        fee_minor as other_rounding_minor,
        amount_minor as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        {{ fmt_money('fee_minor') }} || ' per refund = ' || {{ fmt_money('fee_minor') }} || ' ' || contract_currency
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from refunds
),

markup_credit_rows as (
    select
        'refund' as event_type, event_id, provider, provider_month as month, 'markup_credit' as component,
        contract_id, contract_version, clause, contract_currency,
        -original_markup_minor as expected_minor,
        -other_original_markup_minor as other_rounding_minor,
        amount_minor as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        '−(markup of ' || original_payment_id || ': ' || original_markup_formula || ') = '
            || {{ fmt_money('-original_markup_minor') }} || ' ' || contract_currency
            || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from refunds
    where credit_original_markup
),

-- Clause 6.x (chargeback_fee).
chargeback_fee_rows as (
    select
        'chargeback' as event_type, c.event_id, c.provider, c.provider_month as month, 'chargeback_fee' as component,
        c.contract_id, c.contract_version, t.clause, c.contract_currency,
        t.amount_minor as expected_minor,
        t.amount_minor as other_rounding_minor,
        c.amount_minor as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        {{ fmt_money('t.amount_minor') }} || ' per chargeback = ' || {{ fmt_money('t.amount_minor') }} || ' '
            || c.contract_currency || ' (' || {{ fmt_clause('c.contract_id', 'c.contract_version', 't.clause') }} || ')'
            as formula,
        c.event_timestamp_utc, c.card_segment, c.contract_file, c.source_file, c.source_row
    from events as c
    inner join terms as t on t.contract_version_id = c.contract_version_id and t.kind = 'chargeback_fee'
    where c.event_type = 'chargeback'
),

-- Payouts: the mid of the hour containing the execution time; EUR payouts need no rate.
payouts as (
    select
        po.*,
        fx.mid,
        case when po.currency = 'EUR' then 1000000 else {{ micros('fx.mid') }} end as mid_micros,
        fx.hour_start_utc as mid_hour_utc
    from events as po
    left join {{ ref('stg_fx__mid_hourly') }} as fx
        on fx.pair = 'EUR' || po.currency
        and fx.hour_start_utc = date_trunc('hour', po.event_timestamp_utc)
    where po.event_type = 'payout'
),

-- Clauses 2.x (payout_fee): fixed per rail, or a share of the EUR equivalent at mid with a minimum and a cap.
-- The EUR equivalent is rounded first, then the fee (two roundings).
payout_fees as (
    select
        po.*,
        t.clause,
        t.fixed_minor,
        t.bps,
        t.min_minor,
        t.cap_minor,
        {{ round_div('cast(po.amount_minor as hugeint) * 1000000', 'po.mid_micros', 'po.rounding_mode') }}
            as eur_equivalent_minor,
        {{ round_div('cast(po.amount_minor as hugeint) * 1000000', 'po.mid_micros', 'po.other_rounding_mode') }}
            as other_eur_equivalent_minor
    from payouts as po
    inner join terms as t
        on t.contract_version_id = po.contract_version_id and t.kind = 'payout_fee' and t.rail = po.rail
),

payout_fee_rows as (
    select
        'payout' as event_type, event_id, provider, provider_month as month, 'payout_fee' as component,
        contract_id, contract_version, clause, contract_currency,
        coalesce(
            fixed_minor,
            least(greatest({{ bps_of('eur_equivalent_minor', 'bps', 'rounding_mode') }}, min_minor), cap_minor)
        ) as expected_minor,
        coalesce(
            fixed_minor,
            least(
                greatest({{ bps_of('other_eur_equivalent_minor', 'bps', 'other_rounding_mode') }}, min_minor),
                cap_minor
            )
        ) as other_rounding_minor,
        eur_equivalent_minor as basis_minor,
        bps as rate_bps,
        cast(null as integer) as tier_no,
        case
            when fixed_minor is not null
                then {{ fmt_money('fixed_minor') }} || ' per ' || rail || ' payout = ' || {{ fmt_money('fixed_minor') }}
            else 'min(max(' || {{ fmt_money('eur_equivalent_minor') }} || ' × ' || {{ fmt_bps('bps') }} || ', '
                || {{ fmt_money('min_minor') }} || '), ' || {{ fmt_money('cap_minor') }} || ') = '
                || {{ fmt_money('least(greatest(' ~ bps_of('eur_equivalent_minor', 'bps', 'rounding_mode') ~ ', min_minor), cap_minor)') }}
                || ' ' || contract_currency || ' on the EUR equivalent ' || {{ fmt_money('amount_minor') }} || ' '
                || currency || ' / ' || cast(coalesce(mid, 1) as varchar) || ' = '
                || {{ fmt_money('eur_equivalent_minor') }}
        end
            || ' ' || contract_currency || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || ')'
            as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from payout_fees
),

-- Clause 4.1 (fx_spread_cap): the largest EUR debit the cap allows, at the execution-hour mid.
fx_caps as (
    select
        po.*,
        t.clause,
        cast(json_extract_string(t.parameters, '$.caps_bps.' || po.currency) as integer) as cap_bps
    from payouts as po
    inner join terms as t on t.contract_version_id = po.contract_version_id and t.kind = 'fx_spread_cap'
    where po.currency <> 'EUR'
),

fx_conversion_rows as (
    select
        'payout' as event_type, event_id, provider, provider_month as month, 'fx_conversion' as component,
        contract_id, contract_version, clause, contract_currency,
        {{ round_div('cast(amount_minor as hugeint) * 10000000000', 'cast(mid_micros as hugeint) * (10000 - cap_bps)', 'rounding_mode') }}
            as expected_minor,
        {{ round_div('cast(amount_minor as hugeint) * 10000000000', 'cast(mid_micros as hugeint) * (10000 - cap_bps)', 'other_rounding_mode') }}
            as other_rounding_minor,
        amount_minor as basis_minor,
        cap_bps as rate_bps,
        cast(null as integer) as tier_no,
        'at most ' || {{ fmt_money('amount_minor') }} || ' ' || currency || ' / (' || cast(mid as varchar)
            || ' × (1 − ' || {{ fmt_bps('cap_bps') }} || ')) = '
            || {{ fmt_money(round_div('cast(amount_minor as hugeint) * 10000000000', 'cast(mid_micros as hugeint) * (10000 - cap_bps)', 'rounding_mode')) }}
            || ' ' || contract_currency || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }}
            || '; mid EUR' || currency || ' ' || strftime(mid_hour_utc, '%Y-%m-%d %H:00 UTC') || ')' as formula,
        event_timestamp_utc, card_segment, contract_file, source_file, source_row
    from fx_caps
),

-- Provider × month rows, under the version in force on the month's first day.
month_markup as (
    select provider, month, sum(expected_minor) as markup_minor, sum(other_rounding_minor) as other_markup_minor
    from markup_rows
    group by provider, month
),

-- Clause 7.4 (monthly_minimum on markup): the top-up to the minimum; credits are not netted.
monthly_minimum_rows as (
    select
        'provider_month' as event_type, cast(null as varchar) as event_id, m.provider, m.provider_month as month,
        'monthly_minimum' as component,
        m.contract_id, m.contract_version, t.clause, m.currency as contract_currency,
        greatest(0, t.amount_minor - coalesce(mm.markup_minor, 0)) as expected_minor,
        greatest(0, t.amount_minor - coalesce(mm.other_markup_minor, 0)) as other_rounding_minor,
        coalesce(mm.markup_minor, 0) as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        'max(0, ' || {{ fmt_money('t.amount_minor') }} || ' − ' || {{ fmt_money('coalesce(mm.markup_minor, 0)') }}
            || ' expected markup) = ' || {{ fmt_money('greatest(0, t.amount_minor - coalesce(mm.markup_minor, 0))') }}
            || ' ' || m.currency || ' (' || {{ fmt_clause('m.contract_id', 'm.contract_version', 't.clause') }} || ')'
            as formula,
        cast(null as timestamp) as event_timestamp_utc,
        cast(null as varchar) as card_segment,
        m.contract_file,
        cast(null as varchar) as source_file,
        cast(null as bigint) as source_row
    from months as m
    inner join terms as t
        on t.contract_version_id = m.contract_version_id and t.kind = 'monthly_minimum' and t.applies_to = 'markup'
    left join month_markup as mm on mm.provider = m.provider and mm.month = m.provider_month
),

-- Clause 3.4 (volume_discount, marginal, settled monthly): a credit of the rate difference on the segment
-- volume above the first tier's bound.
volume_discounts as (
    select
        m.*,
        t.clause,
        t.segment,
        case t.segment
            when 'eea_consumer' then m.eea_consumer_volume_minor
            when 'other' then m.other_volume_minor
        end as segment_volume_minor,
        first_tier.up_to_minor as threshold_minor,
        first_tier.bps as first_bps,
        second_tier.bps as second_bps
    from months as m
    inner join terms as t
        on t.contract_version_id = m.contract_version_id
        and t.kind = 'volume_discount'
        and t.tiering = 'marginal'
        and json_extract_string(t.parameters, '$.settlement') = 'monthly_adjustment'
    inner join tiers as first_tier on first_tier.contract_term_id = t.contract_term_id and first_tier.tier_no = 1
    inner join tiers as second_tier on second_tier.contract_term_id = t.contract_term_id and second_tier.tier_no = 2
),

volume_adjustment_rows as (
    select
        'provider_month' as event_type, cast(null as varchar) as event_id, provider, provider_month as month,
        'volume_adjustment' as component,
        contract_id, contract_version, clause, currency as contract_currency,
        case
            when segment_volume_minor <= threshold_minor then 0
            else -{{ bps_of('segment_volume_minor - threshold_minor', 'first_bps - second_bps', 'rounding_mode') }}
        end as expected_minor,
        case
            when segment_volume_minor <= threshold_minor then 0
            else -{{ bps_of('segment_volume_minor - threshold_minor', 'first_bps - second_bps', 'other_rounding_mode') }}
        end as other_rounding_minor,
        segment_volume_minor as basis_minor,
        first_bps - second_bps as rate_bps,
        cast(null as integer) as tier_no,
        case
            when segment_volume_minor <= threshold_minor
                then segment || ' volume ' || {{ fmt_money('segment_volume_minor') }} || ' ≤ '
                    || {{ fmt_money('threshold_minor') }} || ': no discount = 0.00'
            else '−(' || {{ fmt_money('segment_volume_minor') }} || ' − ' || {{ fmt_money('threshold_minor') }}
                || ') × (' || {{ fmt_bps('first_bps') }} || ' − ' || {{ fmt_bps('second_bps') }} || ') = '
                || {{ fmt_money('-' ~ bps_of('segment_volume_minor - threshold_minor', 'first_bps - second_bps', 'rounding_mode')) }}
        end
            || ' ' || currency || ' (' || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || ')'
            as formula,
        cast(null as timestamp) as event_timestamp_utc,
        cast(null as varchar) as card_segment,
        contract_file,
        cast(null as varchar) as source_file,
        cast(null as bigint) as source_row
    from volume_discounts
),

{% set common_columns -%}
    event_type, event_id, provider, month, component, contract_id, contract_version, clause, expected_minor,
    contract_currency, other_rounding_minor, basis_minor, rate_bps, tier_no, formula, event_timestamp_utc, card_segment,
    contract_file, source_file, source_row
{%- endset %}

all_rows as (
    {% for cte in [
        'interchange_rows', 'scheme_fee_rows', 'markup_rows', 'fixed_fee_rows', 'transaction_fee_rows',
        'refund_fee_rows', 'markup_credit_rows', 'chargeback_fee_rows', 'payout_fee_rows', 'fx_conversion_rows',
        'monthly_minimum_rows', 'volume_adjustment_rows'
    ] %}
    select {{ common_columns }} from {{ cte }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    event_type || ':' || coalesce(event_id, provider || ':' || strftime(month, '%Y-%m')) || ':' || component
        as expected_charge_id,
    event_type,
    event_id,
    provider,
    month,
    component,
    contract_id,
    cast(contract_version as integer) as contract_version,
    clause,
    cast(expected_minor as bigint) as expected_minor,
    contract_currency as currency,
    cast(other_rounding_minor as bigint) as other_rounding_minor,
    basis_minor,
    rate_bps,
    tier_no,
    formula,
    event_timestamp_utc,
    card_segment,
    concat_ws(
        '; ',
        case when source_file is not null then source_file || ':' || source_row end,
        contract_file || ' §' || clause
    ) as evidence
from all_rows
