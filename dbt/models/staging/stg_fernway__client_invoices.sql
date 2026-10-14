select
    trim(invoice_id) as invoice_id,
    trim(client_id) as client_id,
    {{ month_start('period') }} as period_month,
    cast(invoice_date as date) as invoice_date,
    {{ normalize_currency('currency') }} as currency,
    {{ minor_to_bigint('total_minor') }} as total_minor,
    source_file,
    source_row
from {{ source('raw', 'fernway__client_invoices') }}
