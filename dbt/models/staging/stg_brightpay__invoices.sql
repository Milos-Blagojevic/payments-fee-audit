select
    trim(invoice_id) as invoice_id,
    'brightpay' as provider,
    {{ month_start('billing_month') }} as statement_month,
    cast(issued_on as date) as invoice_date,
    {{ minor_to_bigint('total') }} as total_minor,
    {{ normalize_currency('currency') }} as currency,
    source_file,
    source_row
from {{ source('raw', 'brightpay__invoices') }}
