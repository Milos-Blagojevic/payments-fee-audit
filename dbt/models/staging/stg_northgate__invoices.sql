select
    trim(invoice_no) as invoice_id,
    'northgate' as provider,
    {{ month_start('period') }} as statement_month,
    cast(invoice_date as date) as invoice_date,
    {{ major_to_minor('total_amount') }} as total_minor,
    {{ normalize_currency('currency') }} as currency,
    source_file,
    source_row
from {{ source('raw', 'northgate__invoices') }}
