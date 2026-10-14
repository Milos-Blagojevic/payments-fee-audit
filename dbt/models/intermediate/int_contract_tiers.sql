-- One row per tier of every tiered term (provider markups and volume discounts, client volume discounts).
-- `up_to_minor` is an exclusive upper bound; a tier starts at the previous tier's bound.
with tiered_terms as (
    select
        contract_term_id,
        contract_version_id,
        contract_id,
        contract_version,
        clause,
        kind,
        tiering,
        from_json(
            parameters -> 'tiers', '[{"up_to_minor": "BIGINT", "bps": "INTEGER", "discount_pct": "INTEGER"}]'
        ) as tiers
    from {{ ref('stg_contracts__contract_terms') }}
    where json_exists(parameters, '$.tiers')
),

numbered as (
    select
        t.*,
        unnest(generate_series(1, len(t.tiers))) as tier_no
    from tiered_terms as t
)

select
    contract_term_id || ' tier ' || tier_no as contract_tier_id,
    contract_term_id,
    contract_version_id,
    contract_id,
    contract_version,
    clause,
    kind,
    tiering,
    tier_no,
    cast(coalesce(tiers[tier_no - 1].up_to_minor, 0) as bigint) as from_minor,
    tiers[tier_no].up_to_minor as up_to_minor,
    tiers[tier_no].bps as bps,
    tiers[tier_no].discount_pct as discount_pct
from numbered
