select
    trim(client_id) as client_id,
    trim(client_name) as client_name,
    upper(trim(country)) as country,
    lower(trim(card_provider)) as card_provider,
    cast(card_provider_switch_date as date) as card_provider_switch_date,
    lower(trim(card_provider_after_switch)) as card_provider_after_switch,
    source_file,
    source_row
from {{ source('raw', 'fernway__clients') }}
