-- M01 per provider × UTC month × card segment: succeeded card payment amounts in the ledger, by event date in UTC.
select
    provider || ':' || strftime(month, '%Y-%m') || ':' || card_segment as processed_volume_id,
    provider,
    month,
    card_segment,
    payments,
    volume_minor
from (
    select
        provider,
        cast(date_trunc('month', event_timestamp_utc) as date) as month,
        card_segment,
        count(*) as payments,
        sum(amount_minor) as volume_minor
    from {{ ref('int_ledger_events') }}
    where event_type = 'payment' and payment_status = 'succeeded'
    group by all
)
