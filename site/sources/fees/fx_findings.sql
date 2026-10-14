-- Conversions with an FX finding (main.fct_fx_conversions).
select
    payout_id,
    line_id,
    executed_at_utc,
    strftime(month, '%Y-%m') as month_label,
    currency,
    rail,
    amount_minor,
    mid_rate::double as mid_rate,
    applied_rate::double as applied_rate,
    rate_timestamp_utc,
    rate_hour_matches,
    spread_bps::double as spread_bps,
    cap_bps,
    spread_cost_minor::bigint as spread_cost_minor,
    over_cap_cost_minor::bigint as over_cap_cost_minor,
    finding_type,
    contract_id,
    contract_version,
    clause,
    contract_id || ' v' || contract_version::varchar || ' §' || clause as term
from main.fct_fx_conversions
where finding_type is not null
