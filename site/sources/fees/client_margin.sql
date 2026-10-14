-- Client × month billing, revenue leakage (M09), allocated provider costs and margin (M10) (main.fct_client_margin).
select
    client_margin_id,
    client_id,
    month,
    strftime(month, '%Y-%m') as month_label,
    volume_minor::bigint as volume_minor,
    billed_minor::bigint as billed_minor,
    expected_minor::bigint as expected_minor,
    revenue_leakage_minor::bigint as revenue_leakage_minor,
    event_provider_fees_minor::bigint as event_provider_fees_minor,
    volume_share_provider_fees_minor::bigint as volume_share_provider_fees_minor,
    provider_fees_minor::bigint as provider_fees_minor,
    fx_spread_cost_minor::bigint as fx_spread_cost_minor,
    provider_cost_minor::bigint as provider_cost_minor,
    margin_minor::bigint as margin_minor,
    margin_bps::double as margin_bps,
    pending_provider_fees_minor::bigint as pending_provider_fees_minor,
    currency
from main.fct_client_margin
