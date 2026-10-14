-- FX conversions per UTC month × currency (main.fct_fx_conversions): count, M08 spread cost, cost above the cap.
select
    month,
    strftime(month, '%Y-%m') as month_label,
    currency,
    any_value(cap_bps) as cap_bps,
    count(*) as conversions,
    count(*) filter (where comparison_status = 'compared') as compared,
    sum(eur_at_mid_minor)::bigint as eur_at_mid_minor,
    sum(spread_cost_minor)::bigint as spread_cost_minor,
    sum(over_cap_cost_minor)::bigint as over_cap_cost_minor,
    count(*) filter (where finding_type = 'fx_spread_above_cap') as spread_above_cap_findings,
    count(*) filter (where finding_type = 'fx_rate_wrong_hour') as wrong_hour_findings
from main.fct_fx_conversions
group by all
order by month, currency
