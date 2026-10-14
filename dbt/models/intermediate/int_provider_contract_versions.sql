select
    contract_version_id,
    counterparty as provider,
    contract_id,
    contract_version,
    lag(contract_version) over (partition by contract_id order by contract_version) as previous_contract_version,
    contract_name,
    effective_from,
    effective_to,
    currency,
    timezone,
    rounding_mode,
    {{ other_rounding_mode('rounding_mode') }} as other_rounding_mode,
    rounding_level,
    dispute_window_days,
    source_file
from {{ ref('stg_contracts__contract_versions') }}
where party = 'provider'
