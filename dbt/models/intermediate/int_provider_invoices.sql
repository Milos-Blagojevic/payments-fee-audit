select invoice_id, provider, statement_month, invoice_date, total_minor, currency, source_file, source_row
from {{ ref('stg_northgate__invoices') }}
union all
select invoice_id, provider, statement_month, invoice_date, total_minor, currency, source_file, source_row
from {{ ref('stg_brightpay__invoices') }}
union all
select invoice_id, provider, statement_month, invoice_date, total_minor, currency, source_file, source_row
from {{ ref('stg_kestrel__invoices') }}
