select
    upper(trim(pair)) as pair,
    'EUR' as base_currency,
    right(upper(trim(pair)), 3) as quote_currency,
    {{ utc_from_iso('hour_start_utc') }} as hour_start_utc,
    cast(mid as decimal(18, 6)) as mid,
    source_file,
    source_row
from {{ source('raw', 'fx__mid_hourly') }}
