-- The provider comparison prices each payment under its own provider's contract exactly as int_expected_charges
-- does (payment-level components of succeeded payments), per provider × UTC month.
with comparison as (
    select actual_provider as provider, month, sum(actual_expected_minor) as expected_minor
    from {{ ref('fct_provider_comparison') }}
    group by all
),

expected as (
    select provider, cast(date_trunc('month', event_timestamp_utc) as date) as month, sum(expected_minor) as expected_minor
    from {{ ref('int_expected_charges') }}
    where event_type = 'payment'
    group by all
)

select coalesce(c.provider, e.provider) as provider, coalesce(c.month, e.month) as month, c.expected_minor, e.expected_minor
from comparison as c
full outer join expected as e on e.provider = c.provider and e.month = c.month
where c.expected_minor is distinct from e.expected_minor
