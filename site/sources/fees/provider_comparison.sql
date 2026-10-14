-- Actual against alternative card provider contract (main.fct_provider_comparison, A23).
select
    provider_comparison_id,
    card_segment,
    month,
    strftime(month, '%Y-%m') as month_label,
    actual_provider,
    alternative_provider,
    payments,
    volume_minor::bigint as volume_minor,
    actual_billed_minor::bigint as actual_billed_minor,
    actual_expected_minor::bigint as actual_expected_minor,
    alternative_expected_minor::bigint as alternative_expected_minor,
    saving_minor::bigint as saving_minor,
    actual_rate_bps::double as actual_rate_bps,
    alternative_rate_bps::double as alternative_rate_bps
from main.fct_provider_comparison
