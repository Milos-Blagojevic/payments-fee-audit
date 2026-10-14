{% set fallback_window_hours = 48 %}

with ledger as (
    select * from {{ ref('int_ledger_events') }}
),

watermark as (
    select watermark_utc from {{ ref('int_ledger_watermark') }}
),

-- One row per provider line; a Kestrel line carries two components but is matched once.
lines as (
    select
        line_id, provider, event_ref, event_type, match_slot, client_id, event_amount_minor, event_currency,
        event_timestamp_utc, event_month, statement_month, source_file, source_row
    from {{ ref('int_provider_lines') }}
    where component <> 'fx_conversion'
),

-- 1. Provider reference. The first line of an event × slot (by statement month, then line id) is the match;
--    any further line of the same event × slot under another line id is a duplicate charge (D06).
by_reference as (
    select
        l.line_id,
        e.event_id,
        row_number() over (
            partition by e.event_id, l.match_slot order by l.statement_month, l.line_id
        ) as slot_rank,
        first_value(l.line_id) over (
            partition by e.event_id, l.match_slot order by l.statement_month, l.line_id
        ) as first_line_id
    from lines as l
    inner join ledger as e
        on e.event_id = l.event_ref
        and e.event_type = l.event_type
        and e.provider = l.provider
),

-- 2. Fallback (N06) for lines without a reference: same provider, event type, client, amount and currency
--    within ±48 h, among ledger event × slots not matched by reference. A pair is kept only when each side is
--    the other's closest candidate (ties: event id, line id), which makes the match one-to-one.
fallback_candidates as (
    select
        l.line_id,
        l.match_slot,
        e.event_id,
        abs(epoch(l.event_timestamp_utc) - epoch(e.event_timestamp_utc)) as seconds_apart
    from lines as l
    inner join ledger as e
        on e.provider = l.provider
        and e.event_type = l.event_type
        and e.client_id = l.client_id
        and e.amount_minor = l.event_amount_minor
        and e.currency = l.event_currency
        and e.event_timestamp_utc between l.event_timestamp_utc - interval {{ fallback_window_hours }} hour
            and l.event_timestamp_utc + interval {{ fallback_window_hours }} hour
    where l.event_ref is null
        and l.event_type <> 'provider_month'
        and not exists (
            select 1
            from by_reference as r
            inner join lines as rl on rl.line_id = r.line_id
            where r.event_id = e.event_id and rl.match_slot = l.match_slot
        )
),

by_fallback as (
    select line_id, event_id
    from fallback_candidates
    qualify
        row_number() over (partition by line_id order by seconds_apart, event_id) = 1
        and row_number() over (partition by event_id, match_slot order by seconds_apart, line_id) = 1
),

-- Months with ledger events per provider (for monthly lines such as minimums and volume adjustments).
ledger_months as (
    select distinct provider, provider_month from ledger
),

line_status as (
    select
        l.line_id as reconciliation_id,
        l.provider,
        l.line_id,
        coalesce(r.event_id, f.event_id) as event_id,
        l.event_type,
        l.match_slot,
        case
            when r.line_id is not null then 'reference'
            when f.line_id is not null then 'fallback'
            when l.event_type = 'provider_month' and m.provider is not null then 'provider_month'
        end as match_method,
        case
            when r.slot_rank > 1 then 'provider_only'
            when r.line_id is not null or f.line_id is not null then 'matched'
            when l.event_type = 'provider_month' and m.provider is not null then 'matched'
            when l.event_type <> 'provider_month' and l.event_timestamp_utc >= w.watermark_utc
                then 'unmatched_pending'
            else 'provider_only'
        end as status,
        case
            when r.slot_rank > 1 then 'duplicate'
            when r.line_id is not null or f.line_id is not null then null
            when l.event_type = 'provider_month' and m.provider is not null then null
            when l.event_type = 'provider_month' then 'unknown_month'
            when l.event_timestamp_utc >= w.watermark_utc then 'ledger_lag'
            when l.event_ref is not null then 'unknown_event'
            else 'no_ledger_match'
        end as reason,
        case when r.slot_rank > 1 then r.first_line_id end as duplicate_of_line_id,
        l.event_ref,
        l.client_id,
        l.event_timestamp_utc,
        l.event_month,
        l.statement_month,
        l.source_file,
        l.source_row
    from lines as l
    cross join watermark as w
    left join by_reference as r on r.line_id = l.line_id
    left join by_fallback as f on f.line_id = l.line_id
    left join ledger_months as m
        on l.event_type = 'provider_month' and m.provider = l.provider and m.provider_month = l.event_month
),

last_statement as (
    select provider, max(statement_month) as last_statement_month
    from lines
    group by provider
),

-- Ledger events that should have a provider line but have none (matched or duplicate).
ledger_only as (
    select
        e.event_type || ':' || e.event_id as reconciliation_id,
        e.provider,
        cast(null as varchar) as line_id,
        e.event_id,
        e.event_type,
        cast(null as varchar) as match_slot,
        cast(null as varchar) as match_method,
        'ledger_only' as status,
        case
            when s.last_statement_month is null or e.provider_month > s.last_statement_month then 'not_billed_yet'
            else 'no_provider_line'
        end as reason,
        cast(null as varchar) as duplicate_of_line_id,
        cast(null as varchar) as event_ref,
        e.client_id,
        e.event_timestamp_utc,
        e.provider_month as event_month,
        cast(null as date) as statement_month,
        e.source_file,
        e.source_row
    from ledger as e
    left join last_statement as s on s.provider = e.provider
    where e.expects_provider_line
        and not exists (
            select 1 from line_status as ls where ls.event_id = e.event_id and ls.status in ('matched', 'provider_only')
        )
)

select * from line_status
union all
select * from ledger_only
