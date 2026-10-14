-- One row per contract version × clause with a readable statement of the term, for reports and dispute letters.
with terms as (
    select * from {{ ref('stg_contracts__contract_terms') }}
),

versions as (
    select * from {{ ref('stg_contracts__contract_versions') }}
),

tier_text as (
    select
        contract_term_id,
        string_agg(
            case when up_to_minor is null then 'from ' || {{ fmt_money('from_minor') }} else 'below ' || {{ fmt_money('up_to_minor') }} end
            || ': ' || case when bps is not null then {{ fmt_bps('bps') }} else discount_pct || '% discount' end,
            '; ' order by tier_no
        ) as tiers
    from {{ ref('int_contract_tiers') }}
    group by contract_term_id
),

{% set segment_text -%}
    'EEA consumer cards ' || {{ fmt_bps("cast(json_extract_string(t.parameters, '$.segments.eea_consumer.bps') as integer)") }}
    || ' + ' || {{ fmt_money("cast(json_extract_string(t.parameters, '$.segments.eea_consumer.fixed_minor') as bigint)") }}
    || ', other cards ' || {{ fmt_bps("cast(json_extract_string(t.parameters, '$.segments.other.bps') as integer)") }}
    || ' + ' || {{ fmt_money("cast(json_extract_string(t.parameters, '$.segments.other.fixed_minor') as bigint)") }}
    || ' ' || v.currency || ' per successful payment'
{%- endset %}

described as (
    select
        t.*,
        v.party,
        v.counterparty,
        v.contract_name,
        v.effective_from,
        v.effective_to,
        v.currency,
        v.timezone,
        v.rounding_mode,
        v.rounding_level,
        v.dispute_window_days,
        v.source_file,
        case t.kind
            when 'pass_through' then 'Interchange and scheme fees at cost, per the reference table ' || t.reference || '.'
            when 'markup_bps_tiered' then 'Markup on each successful payment by the month''s processed volume ('
                || t.tiering || ', months in ' || v.timezone || '): ' || tt.tiers || '.'
            when 'per_transaction_fixed' then {{ fmt_money('t.amount_minor') }} || ' ' || v.currency
                || ' per successful payment.'
            when 'blended_rate' then {{ segment_text }} || '; no fee on declined or failed attempts.'
            when 'volume_discount' then 'Monthly ' || t.tiering || ' discount on ' || t.segment || ' volume: '
                || tt.tiers || ', settled as a monthly adjustment.'
            when 'refund' then 'Refund fee ' || {{ fmt_money('t.fee_minor') }} || ' ' || v.currency || '; the original markup is '
                || case when t.credit_original_markup then 'credited back.' else 'not credited.' end
            when 'chargeback_fee' then {{ fmt_money('t.amount_minor') }} || ' ' || v.currency || ' per chargeback.'
            when 'monthly_minimum' then 'Monthly minimum ' || t.applies_to || ' of ' || {{ fmt_money('t.amount_minor') }} || ' '
                || v.currency || '; a shortfall is billed as a separate line.'
            when 'payout_fee' then
                case
                    when t.fixed_minor is not null
                        then {{ fmt_money('t.fixed_minor') }} || ' ' || v.currency || ' per ' || t.rail || ' payout.'
                    else {{ fmt_bps('t.bps') }} || ' of the EUR equivalent at mid per ' || t.rail || ' payout, at least '
                        || {{ fmt_money('t.min_minor') }} || ' and at most ' || {{ fmt_money('t.cap_minor') }} || ' ' || v.currency || '.'
                end
            when 'fx_spread_cap' then 'FX spread against the hourly mid at the execution hour at most '
                || array_to_string(
                    list_transform(
                        json_keys(t.parameters, '$.caps_bps'),
                        k -> k || ' ' || {{ fmt_bps("cast(json_extract_string(t.parameters, '$.caps_bps.' || k) as integer)") }}
                    ),
                    ', '
                ) || '.'
            when 'payment_fee_by_segment' then {{ segment_text }} || '.'
            when 'payout_fee_by_rail' then 'Per payout: '
                || array_to_string(
                    list_transform(
                        json_keys(t.parameters, '$.rails'),
                        k -> k || ' ' || {{ fmt_money("cast(json_extract_string(t.parameters, '$.rails.' || k || '.fixed_minor') as bigint)") }}
                    ),
                    ', '
                ) || ' ' || v.currency || '.'
            when 'fx_markup' then {{ fmt_bps('t.bps') }} || ' of the EUR equivalent at mid of each non-EUR payout.'
            when 'platform_fee' then {{ fmt_money('t.amount_minor') }} || ' ' || v.currency || ' per month.'
            when 'volume_discount_tiered' then 'Discount on the month''s payment fees by processed volume ('
                || t.tiering || '): ' || tt.tiers || '.'
            when 'promo_discount' then t.discount_pct || '% off payment fees for payments created up to and including '
                || strftime(t.valid_until, '%Y-%m-%d') || '.'
        end as clause_text
    from terms as t
    inner join versions as v on v.contract_version_id = t.contract_version_id
    left join tier_text as tt on tt.contract_term_id = t.contract_term_id
)

select
    contract_term_id,
    contract_version_id,
    contract_id,
    contract_version,
    party,
    counterparty,
    contract_name,
    clause,
    kind,
    title,
    clause_text,
    components,
    effective_from,
    effective_to,
    currency,
    timezone,
    rounding_mode,
    rounding_level,
    dispute_window_days,
    parameters,
    source_file
from described
