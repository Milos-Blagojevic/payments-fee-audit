-- Expected against billed client invoice lines: one row per client × month × invoice line component that was
-- expected or billed. The expected line is the exact client × month × component sum rounded once (`invoice_line`
-- level, data contract section 1); billed is what Fernway's invoice shows (0 when the line is missing). Every row
-- carries its rule classification (data contract section 5).
with expected_lines as (
    select
        client_id,
        month,
        component,
        min(contract_id) as contract_id,
        max(contract_version) as contract_version,
        min(clause) as clause,
        min(rounding_mode) as rounding_mode,
        sum(exact_amount) as exact_amount,
        count(event_id) as events,
        sum(basis_minor) as basis_minor,
        min(rate_bps) as min_rate_bps,
        max(rate_bps) as max_rate_bps,
        min(fixed_minor) as min_fixed_minor,
        max(fixed_minor) as max_fixed_minor,
        min(discount_pct) as discount_pct,
        min(tier_no) as tier_no,
        min(evidence) filter (where event_id is null) as month_evidence
    from {{ ref('int_expected_client_billing') }}
    group by client_id, month, component
),

invoices as (
    select invoice_id, client_id, period_month as month, invoice_date
    from {{ ref('stg_fernway__client_invoices') }}
),

billed_lines as (
    select
        i.client_id,
        i.month,
        l.component,
        list_sort(list(l.invoice_line_id)) as line_ids,
        sum(l.amount_minor) as billed_minor,
        string_agg(distinct l.source_file, ', ') || ' rows '
            || string_agg(cast(l.source_row as varchar), ', ' order by l.source_row) as line_evidence
    from {{ ref('stg_fernway__client_invoice_lines') }} as l
    inner join invoices as i on i.invoice_id = l.invoice_id
    group by i.client_id, i.month, l.component
),

agreements as (
    select counterparty as client_id, contract_id, contract_version, effective_from, effective_to, rounding_mode,
        dispute_window_days, currency, source_file as contract_file
    from {{ ref('stg_contracts__contract_versions') }}
    where party = 'client'
),

-- The month's payment-fee sum and every tier's discount on it: a billed volume discount that equals a higher
-- tier's discount is `volume_discount_too_high`.
fee_sums as (
    select client_id, month, exact_amount as payment_fee_exact
    from expected_lines
    where component = 'payment_fees'
),

tier_discounts as (
    select
        f.client_id,
        f.month,
        t.tier_no,
        t.discount_pct,
        {{ round_div('-f.payment_fee_exact * t.discount_pct // 100', exact_scale(), 'a.rounding_mode') }}
            as discount_minor
    from fee_sums as f
    inner join agreements as a
        on a.client_id = f.client_id
        and f.month >= a.effective_from
        and (a.effective_to is null or f.month <= a.effective_to)
    inner join {{ ref('int_contract_tiers') }} as t
        on t.contract_id = a.contract_id
        and t.contract_version = a.contract_version
        and t.kind = 'volume_discount_tiered'
),

promo_terms as (
    select a.client_id, a.effective_from, a.effective_to, t.discount_pct, t.valid_until, a.rounding_mode
    from {{ ref('stg_contracts__contract_terms') }} as t
    inner join agreements as a on a.contract_id = t.contract_id and a.contract_version = t.contract_version
    where t.kind = 'promo_discount'
),

compared as (
    select
        coalesce(e.client_id, b.client_id) as client_id,
        coalesce(e.month, b.month) as month,
        coalesce(e.component, b.component) as component,
        e.contract_id,
        e.contract_version,
        e.clause,
        e.rounding_mode,
        e.exact_amount,
        coalesce(e.events, 0) as events,
        e.basis_minor,
        e.min_rate_bps,
        e.max_rate_bps,
        e.min_fixed_minor,
        e.max_fixed_minor,
        e.discount_pct,
        e.tier_no,
        e.month_evidence,
        coalesce({{ round_div('e.exact_amount', exact_scale(), 'e.rounding_mode') }}, 0) as expected_minor,
        coalesce(
            {{ round_div('e.exact_amount', exact_scale(), other_rounding_mode('e.rounding_mode')) }}, 0
        ) as other_rounding_minor,
        coalesce(b.line_ids, []::varchar[]) as line_ids,
        coalesce(b.billed_minor, 0) as billed_minor,
        b.line_evidence
    from expected_lines as e
    full outer join billed_lines as b
        on b.client_id = e.client_id and b.month = e.month and b.component = e.component
),

enriched as (
    select
        c.*,
        c.billed_minor - c.expected_minor as difference_minor,
        i.invoice_id,
        i.invoice_date,
        a.contract_id as month_contract_id,
        a.contract_version as month_contract_version,
        a.dispute_window_days,
        a.currency,
        a.contract_file,
        bt.tier_no as billed_tier_no,
        bt.discount_pct as billed_discount_pct,
        p.discount_pct as promo_discount_pct,
        p.valid_until as promo_valid_until,
        -- The promotion's discount on every payment fee of the month, end date ignored.
        case when c.component = 'promo_discount' then
            {{ round_div('-f.payment_fee_exact * p.discount_pct // 100', exact_scale(), 'p.rounding_mode') }}
        end as promo_whole_month_minor
    from compared as c
    left join invoices as i on i.client_id = c.client_id and i.month = c.month
    left join agreements as a
        on a.client_id = c.client_id
        and c.month >= a.effective_from
        and (a.effective_to is null or c.month <= a.effective_to)
    left join fee_sums as f on f.client_id = c.client_id and f.month = c.month
    left join promo_terms as p
        on p.client_id = c.client_id
        and c.month >= p.effective_from
        and (p.effective_to is null or c.month <= p.effective_to)
    -- The highest tier whose discount equals the billed one (tiers with the same rounded discount: the highest).
    left join (
        select client_id, month, max(tier_no) as tier_no, arg_max(discount_pct, tier_no) as discount_pct, discount_minor
        from tier_discounts
        group by client_id, month, discount_minor
    ) as bt
        on c.component = 'volume_discount'
        and bt.client_id = c.client_id
        and bt.month = c.month
        and bt.discount_minor = c.billed_minor
)

select
    client_id || ':' || strftime(month, '%Y-%m') || ':' || component as client_billing_line_id,
    client_id,
    month,
    component,
    coalesce(contract_id, month_contract_id) as contract_id,
    coalesce(contract_version, month_contract_version) as contract_version,
    clause,
    contract_file,
    dispute_window_days,
    currency,
    invoice_id,
    invoice_date,
    line_ids,
    len(line_ids) as line_count,
    events,
    exact_amount,
    expected_minor,
    other_rounding_minor,
    billed_minor,
    difference_minor,
    tier_no,
    discount_pct,
    billed_tier_no,
    billed_discount_pct,
    promo_valid_until,
    promo_whole_month_minor,
    case
        when abs(difference_minor) < 1 then null
        when component like 'payout_fees_%' and len(line_ids) = 0 and expected_minor > 0 then 'rail_not_billed'
        when component = 'fx_markup' and len(line_ids) = 0 and expected_minor > 0 then 'fx_markup_not_billed'
        when component = 'promo_discount'
            and billed_minor < expected_minor
            and billed_minor = promo_whole_month_minor
            and promo_valid_until < cast(month + interval 1 month - interval 1 day as date)
            then 'promo_after_end_date'
        when component = 'volume_discount' and billed_minor < expected_minor and billed_tier_no > tier_no
            then 'volume_discount_too_high'
        when abs(difference_minor) = 1 and billed_minor = other_rounding_minor then 'rounding'
        else 'fee_mismatch'
    end as finding_type,
    -- The calculation with real numbers, by component.
    case
        when component = 'payment_fees' then
            events || ' succeeded payments, volume ' || {{ fmt_money('basis_minor') }} || ' EUR, at '
            || case when min_rate_bps = max_rate_bps then {{ fmt_bps('min_rate_bps') }}
                else {{ fmt_bps('min_rate_bps') }} || '–' || {{ fmt_bps('max_rate_bps') }} end
            || ' + ' || case when min_fixed_minor = max_fixed_minor then {{ fmt_money('min_fixed_minor') }}
                else {{ fmt_money('min_fixed_minor') }} || '–' || {{ fmt_money('max_fixed_minor') }} end
            || ' by card segment, summed exactly and rounded once'
        when component like 'payout_fees_%' then
            events || ' ' || replace(component, 'payout_fees_', '') || ' payouts × ' || {{ fmt_money('min_fixed_minor') }}
        when component = 'fx_markup' then
            {{ fmt_bps('min_rate_bps') }} || ' of the EUR equivalent at mid ' || {{ fmt_money('basis_minor') }} || ' of '
            || events || ' non-EUR payouts'
        when component = 'platform_fee' then 'monthly platform fee'
        when component = 'volume_discount' then
            'month volume ' || {{ fmt_money('basis_minor') }} || ' EUR is in tier ' || tier_no || ' (' || discount_pct
            || '% of the unrounded payment fees)'
            || coalesce('; the billed discount is tier ' || billed_tier_no || '''s ' || billed_discount_pct || '%', '')
        when component = 'promo_discount' then
            discount_pct || '% of the payment fees of payments created up to ' || strftime(promo_valid_until, '%Y-%m-%d')
            || case when billed_minor = promo_whole_month_minor and billed_minor <> expected_minor
                then '; the billed discount covers the whole month' else '' end
        else 'no term of the agreement bills this component'
    end
        || ': expected ' || {{ fmt_money('expected_minor') }} || ', billed ' || {{ fmt_money('billed_minor') }}
        || ' EUR' || case when len(line_ids) = 0 then ' (no invoice line)' else '' end
        || coalesce(' (' || {{ fmt_clause(
            'coalesce(contract_id, month_contract_id)', 'coalesce(contract_version, month_contract_version)', 'clause'
        ) }} || ')', '')
        as formula,
    coalesce(
        invoice_id || ' lines ' || array_to_string(line_ids, ', ') || ' (' || line_evidence || ')',
        coalesce(invoice_id, 'no invoice') || ': no ' || component || ' line'
    )
        || '; ' || case
            when events > 0 then
                events || case when component = 'payment_fees' then ' succeeded ledger payments' else ' ledger payouts' end
                || ' of ' || client_id || ' in ' || strftime(month, '%Y-%m')
                || coalesce('; ' || contract_file || ' §' || clause, '')
            else coalesce(month_evidence, 'no expected charge')
        end as evidence
from enriched
