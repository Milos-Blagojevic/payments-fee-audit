-- Provider fees by provider × month × component × card segment (main.fct_provider_costs): M01–M04.
select
    provider_cost_id,
    provider,
    month,
    strftime(month, '%Y-%m') as month_label,
    component,
    card_segment,
    lines::bigint as lines,
    billed_minor::bigint as billed_minor,
    pending_billed_minor::bigint as pending_billed_minor,
    expected_minor::bigint as expected_minor,
    difference_minor::bigint as difference_minor,
    volume_minor::bigint as volume_minor,
    effective_rate_bps::double as effective_rate_bps
from main.fct_provider_costs
