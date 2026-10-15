-- One row per provider with a contract: its name and how its card payments are priced (M04 covers interchange++).
select
    counterparty as provider,
    arg_max(contract_name, effective_from) as provider_name,
    case
        when bool_or(kind = 'markup_bps_tiered') then 'interchange_plus_plus'
        when bool_or(kind = 'blended_rate') then 'blended'
        else 'not_applicable'
    end as pricing_model
from {{ ref('dim_contract_terms') }}
where party = 'provider'
group by counterparty
