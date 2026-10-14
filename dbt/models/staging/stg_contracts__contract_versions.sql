select
    contract_id || ' v' || version as contract_version_id,
    contract_id,
    version as contract_version,
    party,
    counterparty,
    name as contract_name,
    effective_from,
    effective_to,
    currency,
    timezone,
    rounding_mode,
    rounding_level,
    dispute_window_days,
    source_file
from {{ source('contracts', 'contract_versions') }}
