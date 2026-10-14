-- Realised spread minus the contractual cap, in whole basis points (floor), per currency (main.fct_fx_conversions).
select
    currency,
    any_value(cap_bps) as cap_bps,
    floor(spread_bps - cap_bps)::integer as bps_vs_cap,
    count(*) as conversions,
    sum(over_cap_cost_minor)::bigint as over_cap_cost_minor
from main.fct_fx_conversions
where spread_bps is not null
group by all
order by currency, bps_vs_cap
