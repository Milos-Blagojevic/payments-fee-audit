-- What each card segment's volume cost at its actual provider and what it would have cost under the other card
-- provider's contract, per UTC month (A23). Payment-level fees only: each payment priced under every card contract
-- version in force at its time, the alternative's volume tier taken from that provider's actual month volume.
with payments as (
    select *
    from {{ ref('int_ledger_events') }}
    where event_type = 'payment' and payment_status = 'succeeded'
),

terms as (
    select * from {{ ref('stg_contracts__contract_terms') }}
),

card_versions as (
    select v.*
    from {{ ref('int_provider_contract_versions') }} as v
    where exists (
        select 1 from terms as t
        where t.contract_version_id = v.contract_version_id
            and t.kind in ('pass_through', 'markup_bps_tiered', 'per_transaction_fixed', 'blended_rate')
    )
),

-- Every payment under every card contract (its own provider's and the others').
priced as (
    select
        p.event_id,
        p.provider as actual_provider,
        p.card_scheme,
        p.card_type,
        p.card_region,
        p.card_segment,
        p.amount_minor,
        cast(date_trunc('month', p.event_timestamp_utc) as date) as month,
        v.provider as priced_provider,
        v.contract_version_id,
        v.rounding_mode,
        cast(date_trunc('month', {{ local_from_utc('p.event_timestamp_utc', 'v.timezone') }}) as date) as priced_month
    from payments as p
    inner join card_versions as v
        on cast({{ local_from_utc('p.event_timestamp_utc', 'v.timezone') }} as date)
            between v.effective_from and coalesce(v.effective_to, date '9999-12-31')
),

term_costs as (
    -- pass_through: interchange and scheme fee from the reference table.
    select
        pr.event_id, pr.priced_provider,
        {{ bps_of('pr.amount_minor', 'i.interchange_bps', 'pr.rounding_mode') }}
            + {{ bps_of('pr.amount_minor', 'i.scheme_fee_bps', 'pr.rounding_mode') }} + i.scheme_fee_fixed_minor
            as cost_minor
    from priced as pr
    inner join terms as t on t.contract_version_id = pr.contract_version_id and t.kind = 'pass_through'
    inner join {{ ref('interchange_table_v1') }} as i
        on i.reference = t.reference
        and i.card_scheme = pr.card_scheme
        and i.card_type = pr.card_type
        and i.card_region = pr.card_region

    union all

    -- markup_bps_tiered (retroactive): the tier of the priced provider's actual month volume.
    select
        pr.event_id, pr.priced_provider,
        {{ bps_of('pr.amount_minor', 'r.bps', 'pr.rounding_mode') }}
    from priced as pr
    inner join terms as t
        on t.contract_version_id = pr.contract_version_id and t.kind = 'markup_bps_tiered' and t.tiering = 'retroactive'
    left join {{ ref('int_provider_months') }} as m
        on m.provider = pr.priced_provider and m.provider_month = pr.priced_month
    inner join {{ ref('int_contract_tiers') }} as r
        on r.contract_term_id = t.contract_term_id
        and coalesce(m.volume_minor, 0) >= r.from_minor
        and (r.up_to_minor is null or coalesce(m.volume_minor, 0) < r.up_to_minor)

    union all

    select pr.event_id, pr.priced_provider, t.amount_minor
    from priced as pr
    inner join terms as t on t.contract_version_id = pr.contract_version_id and t.kind = 'per_transaction_fixed'

    union all

    -- blended_rate: the segment's all-in rate.
    select
        pr.event_id, pr.priced_provider,
        {{ bps_of('pr.amount_minor', "cast(json_extract_string(t.parameters, '$.segments.' || pr.card_segment || '.bps') as integer)", 'pr.rounding_mode') }}
            + cast(json_extract_string(t.parameters, '$.segments.' || pr.card_segment || '.fixed_minor') as bigint)
    from priced as pr
    inner join terms as t on t.contract_version_id = pr.contract_version_id and t.kind = 'blended_rate'
),

payment_costs as (
    select
        pr.event_id,
        pr.actual_provider,
        pr.priced_provider,
        pr.card_segment,
        pr.month,
        pr.amount_minor,
        coalesce(sum(tc.cost_minor), 0) as cost_minor
    from priced as pr
    left join term_costs as tc on tc.event_id = pr.event_id and tc.priced_provider = pr.priced_provider
    group by all
),

billed as (
    select event_id, sum(billed_minor) as billed_minor
    from {{ ref('int_charge_comparison') }}
    where event_type = 'payment'
    group by event_id
),

compared as (
    select
        a.card_segment,
        a.month,
        a.actual_provider,
        o.priced_provider as alternative_provider,
        count(*) as payments,
        sum(a.amount_minor) as volume_minor,
        sum(a.cost_minor) as actual_expected_minor,
        sum(coalesce(b.billed_minor, 0)) as actual_billed_minor,
        sum(o.cost_minor) as alternative_expected_minor
    from payment_costs as a
    inner join payment_costs as o on o.event_id = a.event_id and o.priced_provider <> a.priced_provider
    left join billed as b on b.event_id = a.event_id
    where a.priced_provider = a.actual_provider
    group by all
)

select
    card_segment || ':' || strftime(month, '%Y-%m') || ':' || actual_provider || ':' || alternative_provider
        as provider_comparison_id,
    card_segment,
    month,
    actual_provider,
    alternative_provider,
    payments,
    volume_minor,
    actual_billed_minor,
    actual_expected_minor,
    alternative_expected_minor,
    actual_expected_minor - alternative_expected_minor as saving_minor,
    {{ rate_bps('actual_expected_minor', 'volume_minor') }} as actual_rate_bps,
    {{ rate_bps('alternative_expected_minor', 'volume_minor') }} as alternative_rate_bps
from compared
