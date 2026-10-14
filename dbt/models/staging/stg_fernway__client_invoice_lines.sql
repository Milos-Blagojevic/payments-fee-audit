select
    trim(invoice_id) || ':' || trim(line_no) as invoice_line_id,
    trim(invoice_id) as invoice_id,
    cast(line_no as integer) as line_no,
    lower(trim(component)) as component,
    description,
    cast(quantity as bigint) as quantity,
    {{ minor_to_bigint('amount_minor') }} as amount_minor,
    source_file,
    source_row
from {{ source('raw', 'fernway__client_invoice_lines') }}
