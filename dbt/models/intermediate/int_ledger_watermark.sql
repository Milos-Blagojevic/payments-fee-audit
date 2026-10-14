-- N07: the ledger file for export date D holds the events of D - 1 (UTC), so the ledger is complete for every
-- event before 00:00 UTC of the latest export date. All ledger tables are exported together; empty daily files
-- load no rows, so the latest export date seen in any table is the export date of the run.
with latest_exports as (
    select max(export_date) as last_export_date from {{ ref('stg_ledger__payments') }}
    union all
    select max(export_date) from {{ ref('stg_ledger__refunds') }}
    union all
    select max(export_date) from {{ ref('stg_ledger__chargebacks') }}
    union all
    select max(export_date) from {{ ref('stg_ledger__payouts') }}
)

select
    max(last_export_date) as last_export_date,
    cast(max(last_export_date) as timestamp) as watermark_utc
from latest_exports
