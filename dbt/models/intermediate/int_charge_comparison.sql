{#-
    Expected against billed, one row per expected charge (ledger event × component, or provider × month ×
    component) with the matched lines it was billed on, plus one row per provider line component that has no
    ledger counterpart (duplicates, unknown events, lines after the ledger watermark). Every provider line
    component lands in exactly one row. Each row carries the rule classification of its difference
    (data contract section 5); `fct_findings` publishes the rows that are findings.
-#}
with expected as (
    select * from {{ ref('int_expected_charges') }}
),

versions as (
    select * from {{ ref('int_provider_contract_versions') }}
),

terms as (
    select * from {{ ref('stg_contracts__contract_terms') }}
),

tiers as (
    select * from {{ ref('int_contract_tiers') }}
),

fx as (
    select pair, hour_start_utc, {{ micros('mid') }} as mid_micros, mid
    from {{ ref('stg_fx__mid_hourly') }}
),

lines as (
    select
        l.*,
        r.status,
        r.reason,
        r.event_id as matched_event_id,
        r.duplicate_of_line_id
    from {{ ref('int_provider_lines') }} as l
    inner join {{ ref('int_reconciliation') }} as r on r.line_id = l.line_id
),

last_statement as (
    select provider, max(statement_month) as last_statement_month
    from lines
    group by provider
),

ledger_events as (
    select * from {{ ref('int_ledger_events') }}
),

-- Matched lines summed per ledger event × component and per provider × month × component.
billed as (
    select
        case
            when event_type = 'provider_month' then provider || ':' || strftime(event_month, '%Y-%m')
            else matched_event_id
        end || ':' || component as join_key,
        case when event_type = 'provider_month' then null else matched_event_id end as event_id,
        provider,
        event_month,
        event_type,
        component,
        sum(amount_minor) as billed_minor,
        list(line_id order by line_id) as line_ids,
        min(statement_month) as statement_month,
        string_agg(source_file || ':' || source_row, '; ' order by line_id) as line_evidence,
        any_value(fx_rate_applied) as fx_rate_applied,
        any_value(rate_timestamp_utc) as rate_timestamp_utc,
        any_value(event_timestamp_utc) as line_event_timestamp_utc
    from lines
    where status = 'matched'
    group by all
),

-- The statement an event was billed on (any of its lines), for charges that have no line of their own.
event_statements as (
    select matched_event_id as event_id, min(statement_month) as statement_month
    from lines
    where status = 'matched' and matched_event_id is not null
    group by matched_event_id
),

compared as (
    select
        coalesce(
            e.expected_charge_id,
            'billed:' || coalesce(b.event_id, b.provider || ':' || strftime(b.event_month, '%Y-%m')) || ':' || b.component
        ) as comparison_id,
        coalesce(e.event_type, b.event_type) as event_type,
        coalesce(e.event_id, b.event_id) as event_id,
        coalesce(e.provider, b.provider) as provider,
        coalesce(e.month, b.event_month) as month,
        coalesce(e.component, b.component) as component,
        e.contract_id,
        e.contract_version,
        e.clause,
        coalesce(e.expected_minor, 0) as expected_minor,
        coalesce(b.billed_minor, 0) as billed_minor,
        coalesce(e.currency, 'EUR') as currency,
        e.other_rounding_minor,
        e.basis_minor,
        e.rate_bps,
        e.tier_no,
        e.card_segment,
        e.formula,
        e.evidence as expected_evidence,
        coalesce(b.line_ids, []::varchar[]) as line_ids,
        b.line_evidence,
        coalesce(b.statement_month, s.statement_month, coalesce(e.month, b.event_month)) as statement_month,
        b.fx_rate_applied,
        b.rate_timestamp_utc,
        coalesce(e.event_timestamp_utc, b.line_event_timestamp_utc) as event_timestamp_utc,
        cast(null as varchar) as line_status,
        cast(null as varchar) as line_reason,
        cast(null as varchar) as duplicate_of_line_id
    from (
        select
            *,
            case
                when event_type = 'provider_month' then provider || ':' || strftime(month, '%Y-%m')
                else event_id
            end || ':' || component as join_key
        from expected
    ) as e
    full outer join billed as b on b.join_key = e.join_key
    left join event_statements as s on s.event_id = coalesce(e.event_id, b.event_id)
),

-- Lines without a ledger counterpart: expected 0 under the contract version in force at the line's event time.
unmatched_lines as (
    select
        'line:' || l.line_component_id as comparison_id,
        l.event_type,
        l.matched_event_id as event_id,
        l.provider,
        l.event_month as month,
        l.component,
        v.contract_id,
        v.contract_version,
        t.clause,
        0 as expected_minor,
        l.amount_minor as billed_minor,
        l.currency,
        0 as other_rounding_minor,
        cast(null as bigint) as basis_minor,
        cast(null as integer) as rate_bps,
        cast(null as integer) as tier_no,
        cast(null as varchar) as card_segment,
        case l.reason
            when 'duplicate' then l.component || ' of ' || l.matched_event_id || ' is already billed on '
                || l.duplicate_of_line_id || ': expected 0.00 ' || l.currency || ' for a second line'
            when 'unknown_event' then 'no ledger event ' || l.event_ref || ': expected 0.00 ' || l.currency
            when 'no_ledger_match' then 'no ledger event matches this line: expected 0.00 ' || l.currency
            when 'unknown_month' then 'no ledger events in ' || strftime(l.event_month, '%Y-%m') || ': expected 0.00 '
                || l.currency
            else 'not checked yet (' || l.reason || ')'
        end
            || ' (' || {{ fmt_clause('v.contract_id', 'v.contract_version', 't.clause') }} || ')' as formula,
        v.source_file || ' §' || t.clause as expected_evidence,
        [l.line_id] as line_ids,
        l.source_file || ':' || l.source_row as line_evidence,
        l.statement_month,
        l.fx_rate_applied,
        l.rate_timestamp_utc,
        l.event_timestamp_utc,
        l.status as line_status,
        l.reason as line_reason,
        l.duplicate_of_line_id
    from lines as l
    left join versions as v
        on v.provider = l.provider
        and coalesce(
            cast({{ local_from_utc('l.event_timestamp_utc', 'v.timezone') }} as date), l.event_month
        ) between v.effective_from and coalesce(v.effective_to, date '9999-12-31')
    left join terms as t
        on t.contract_version_id = v.contract_version_id
        and list_contains(t.components, l.component)
        and (t.kind <> 'payout_fee' or t.rail = l.rail)
    where l.status in ('provider_only', 'unmatched_pending')
),

rows as (
    select * from compared
    union all by name
    select * from unmatched_lines
),

-- Join keys for the alternative readings, computed once so that every lookup below is a plain equality join.
keyed as (
    select
        r.*,
        v.rounding_mode,
        v.dispute_window_days,
        m.ledger_covers_month,
        ls.last_statement_month,
        e.payment_status,
        e.rail,
        e.currency as event_currency,
        e.amount_minor as event_amount_minor,
        r.contract_id || ' v' || r.contract_version as contract_version_id,
        case when r.component = 'markup' then r.contract_id || ' v' || r.contract_version || ' §' || r.clause end
            as markup_term_id,
        case when r.component = 'markup' then r.contract_id || ' v' || v.previous_contract_version || ' §' || r.clause end
            as previous_markup_term_id,
        case when r.component = 'fx_conversion' then 'EUR' || e.currency end as fx_pair,
        case when r.component = 'fx_conversion' then date_trunc('hour', r.event_timestamp_utc) end as execution_hour_utc
    from rows as r
    left join versions as v on v.contract_id = r.contract_id and v.contract_version = r.contract_version
    left join {{ ref('int_provider_months') }} as m on m.provider = r.provider and m.provider_month = r.month
    left join last_statement as ls on ls.provider = r.provider
    left join ledger_events as e on e.event_id = r.event_id
),

-- Alternative readings the classification compares the billed amount with.
enriched as (
    select
        k.*,
        -- Markup: the previous version's rate for the same tier (stale rate) and the first tier's rate.
        {{ bps_of('k.basis_minor', 'previous_tier.bps', 'k.rounding_mode') }} as previous_version_minor,
        {{ bps_of('k.basis_minor', 'first_tier.bps', 'k.rounding_mode') }} as first_tier_minor,
        first_tier.bps as first_tier_bps,
        previous_tier.bps as previous_version_bps,
        -- Blended fee: the rate of the other card segment.
        {{ bps_of('k.basis_minor', "cast(json_extract_string(blended.parameters, '$.segments.' || case k.card_segment when 'eea_consumer' then 'other' else 'eea_consumer' end || '.bps') as integer)", 'k.rounding_mode') }}
            + cast(json_extract_string(blended.parameters, '$.segments.' || case k.card_segment when 'eea_consumer' then 'other' else 'eea_consumer' end || '.fixed_minor') as bigint)
            as other_segment_minor,
        -- Payout fee: the cap of the rail.
        payout_term.cap_minor as payout_cap_minor,
        -- FX: mids at the execution hour and at the hour of the rate the provider used.
        fx_exec.mid_micros as mid_exec_micros,
        fx_rate.mid_micros as mid_rate_hour_micros,
        {{ micros('k.fx_rate_applied') }} as applied_micros
    from keyed as k
    left join tiers as first_tier on first_tier.contract_term_id = k.markup_term_id and first_tier.tier_no = 1
    left join tiers as previous_tier
        on previous_tier.contract_term_id = k.previous_markup_term_id and previous_tier.tier_no = k.tier_no
    left join (select * from terms where kind = 'blended_rate') as blended
        on k.component = 'transaction_fee' and blended.contract_version_id = k.contract_version_id
    left join (select * from terms where kind = 'payout_fee') as payout_term
        on k.component = 'payout_fee'
        and payout_term.contract_version_id = k.contract_version_id
        and payout_term.rail = k.rail
    left join fx as fx_exec on fx_exec.pair = k.fx_pair and fx_exec.hour_start_utc = k.execution_hour_utc
    left join fx as fx_rate on fx_rate.pair = k.fx_pair and fx_rate.hour_start_utc = k.rate_timestamp_utc
),

statused as (
    select
        *,
        case
            when line_status = 'unmatched_pending' then 'ledger_lag'
            when last_statement_month is null or month > last_statement_month then 'not_billed_yet'
            when event_type = 'provider_month' and not coalesce(ledger_covers_month, false) then 'month_not_covered'
        end as pending_reason,
        -- D12: the debit rescaled to the execution-hour mid, never above the cap allowance.
        case
            when component = 'fx_conversion' and rate_timestamp_utc <> date_trunc('hour', event_timestamp_utc)
                then least(
                    {{ round_div('cast(event_amount_minor as hugeint) * mid_rate_hour_micros * 1000000', 'cast(applied_micros as hugeint) * mid_exec_micros', 'rounding_mode') }},
                    expected_minor
                )
        end as wrong_hour_expected_minor,
        component = 'markup' and billed_minor <> expected_minor and previous_version_minor is not null
            and billed_minor = previous_version_minor as reads_as_stale_rate,
        component = 'markup' and billed_minor <> expected_minor and tier_no > 1
            and billed_minor = first_tier_minor as reads_as_first_tier
    from enriched
),

-- A small markup can round to the same amount at the previous version's rate and at the first tier's rate. Such a
-- line takes the reading that the month's unambiguous markup lines show more often (A21).
month_markup_readings as (
    select
        provider,
        month,
        count(*) filter (where reads_as_stale_rate and not reads_as_first_tier) as stale_only_lines,
        count(*) filter (where reads_as_first_tier and not reads_as_stale_rate) as first_tier_only_lines
    from statused
    where component = 'markup'
    group by provider, month
),

classified as (
    select
        s.*,
        case
            when pending_reason is not null then null
            when line_reason = 'duplicate' and billed_minor <> 0 then 'duplicate_charge'
            when line_reason in ('unknown_event', 'no_ledger_match') and billed_minor <> 0 then 'unknown_charge'
            when component = 'fx_conversion' then
                case
                    when wrong_hour_expected_minor is not null and billed_minor - wrong_hour_expected_minor >= 1
                        then 'fx_rate_wrong_hour'
                    when wrong_hour_expected_minor is null and billed_minor > expected_minor
                        then 'fx_spread_above_cap'
                end
            when billed_minor = expected_minor then null
            when reads_as_stale_rate and reads_as_first_tier
                then case
                    when mr.first_tier_only_lines > mr.stale_only_lines then 'retroactive_tier_not_applied'
                    else 'stale_rate'
                end
            when reads_as_stale_rate then 'stale_rate'
            when reads_as_first_tier then 'retroactive_tier_not_applied'
            when component = 'transaction_fee' and payment_status in ('declined', 'failed') and expected_minor = 0
                then 'fee_on_failed_attempt'
            when component = 'transaction_fee' and card_segment = 'eea_consumer' and billed_minor = other_segment_minor
                then 'wrong_card_segment'
            when component = 'payout_fee' and payout_cap_minor is not null and billed_minor > payout_cap_minor
                then 'payout_fee_cap_not_applied'
            when abs(billed_minor - expected_minor) = 1 and billed_minor = other_rounding_minor then 'rounding'
            when component in ('interchange', 'scheme_fee') and billed_minor > expected_minor
                then 'pass_through_above_reference'
            when component = 'chargeback_fee' then 'chargeback_fee_mismatch'
            when component = 'refund_fee' and billed_minor = 0 and expected_minor > 0 then 'refund_fee_missing'
            when component = 'markup_credit' and billed_minor = 0 and expected_minor < 0 then 'refund_credit_missing'
            when component = 'monthly_minimum' and expected_minor = 0 and billed_minor > 0 then 'minimum_not_due'
            when component = 'volume_adjustment' and billed_minor > expected_minor then 'volume_discount_not_applied'
            else 'fee_mismatch'
        end as finding_type
    from statused as s
    left join month_markup_readings as mr on s.component = 'markup' and mr.provider = s.provider and mr.month = s.month
)

select
    comparison_id,
    case when pending_reason is null then 'compared' else 'pending' end as comparison_status,
    pending_reason,
    event_type,
    event_id,
    provider,
    month,
    component,
    contract_id,
    contract_version,
    clause,
    expected_minor,
    billed_minor,
    billed_minor - expected_minor as difference_minor,
    currency,
    other_rounding_minor,
    finding_type,
    -- The amount the finding is measured against: the rescaled debit for D12, the expected charge otherwise.
    case when finding_type = 'fx_rate_wrong_hour' then wrong_hour_expected_minor else expected_minor end
        as finding_expected_minor,
    basis_minor,
    rate_bps,
    tier_no,
    first_tier_bps,
    previous_version_bps,
    card_segment,
    formula,
    case
        when finding_type = 'fx_rate_wrong_hour'
            then {{ fmt_money('event_amount_minor') }} || ' ' || event_currency || ' / (' || cast(fx_rate_applied as varchar)
                || ' × ' || cast(cast(mid_exec_micros as decimal(18, 6)) / 1000000 as varchar) || ' / '
                || cast(cast(mid_rate_hour_micros as decimal(18, 6)) / 1000000 as varchar) || ') = '
                || {{ fmt_money('wrong_hour_expected_minor') }} || ' ' || currency
                || ' at the execution-hour mid ' || strftime(date_trunc('hour', event_timestamp_utc), '%Y-%m-%d %H:00 UTC')
                || ' instead of the rate hour ' || strftime(rate_timestamp_utc, '%Y-%m-%d %H:00 UTC') || ' ('
                || {{ fmt_clause('contract_id', 'contract_version', 'clause') }} || '; cap ' || formula || ')'
        else formula
    end as finding_formula,
    line_ids,
    len(line_ids) as line_count,
    concat_ws('; ', line_evidence, expected_evidence) as evidence,
    statement_month,
    line_status,
    line_reason,
    duplicate_of_line_id,
    payment_status,
    rail,
    fx_rate_applied,
    rate_timestamp_utc,
    event_timestamp_utc,
    rounding_mode,
    dispute_window_days
from classified
