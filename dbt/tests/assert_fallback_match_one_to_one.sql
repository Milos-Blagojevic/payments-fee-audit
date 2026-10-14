-- The fallback match is one-to-one: no ledger event × slot is matched by more than one line, and no event × slot
-- matched by fallback is also matched by reference.
with matches as (
    select event_id, match_slot, match_method, line_id
    from {{ ref('int_reconciliation') }}
    where status = 'matched' and match_method in ('reference', 'fallback')
)

select event_id, match_slot, count(*) as matched_lines, list(line_id) as line_ids
from matches
where event_id in (select event_id from matches where match_method = 'fallback')
group by event_id, match_slot
having count(*) > 1
