select
    trim(invoice_number) as invoice_id,
    'kestrel' as provider,
    {{ month_start('statement_month') }} as statement_month,
    cast(invoice_date as date) as invoice_date,
    {{ major_to_minor('amount_eur') }} as total_minor,
    {{ normalize_currency('currency') }} as currency,
    source_file,
    source_row
from {{ source('raw', 'kestrel__invoices') }}
