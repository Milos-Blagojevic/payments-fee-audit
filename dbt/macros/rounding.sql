{#-
    Exact integer rounding of numerator / denominator for money (data contract section 1). Arguments are SQL
    expressions; they are evaluated as HUGEINT, so nothing passes through DOUBLE. The denominator must be positive.
    `half_up` rounds ties away from zero; `half_even` rounds ties to the even neighbour.
-#}

{% macro round_half_up(numerator, denominator) -%}
    cast(
        sign(cast({{ numerator }} as hugeint))
        * ((abs(cast({{ numerator }} as hugeint)) * 2 + cast({{ denominator }} as hugeint))
            // (2 * cast({{ denominator }} as hugeint)))
    as bigint)
{%- endmacro %}

{% macro round_half_even(numerator, denominator) -%}
    cast(
        sign(cast({{ numerator }} as hugeint))
        * (
            abs(cast({{ numerator }} as hugeint)) // cast({{ denominator }} as hugeint)
            + case
                when 2 * (abs(cast({{ numerator }} as hugeint)) % cast({{ denominator }} as hugeint))
                        > cast({{ denominator }} as hugeint)
                    then 1
                when 2 * (abs(cast({{ numerator }} as hugeint)) % cast({{ denominator }} as hugeint))
                        = cast({{ denominator }} as hugeint)
                    and (abs(cast({{ numerator }} as hugeint)) // cast({{ denominator }} as hugeint)) % 2 = 1
                    then 1
                else 0
            end
        )
    as bigint)
{%- endmacro %}

{#- Rounding by a mode column or literal; an unknown mode fails the query. -#}
{% macro round_div(numerator, denominator, mode) -%}
    case {{ mode }}
        when 'half_up' then {{ round_half_up(numerator, denominator) }}
        when 'half_even' then {{ round_half_even(numerator, denominator) }}
        else cast(error('unknown rounding mode: ' || coalesce({{ mode }}, 'null')) as bigint)
    end
{%- endmacro %}

{#- The other rounding mode, for the `rounding` finding category (A04). -#}
{% macro other_rounding_mode(mode) -%}
    case {{ mode }} when 'half_up' then 'half_even' when 'half_even' then 'half_up' end
{%- endmacro %}

{#- round(amount × bps / 10000) in the given mode. -#}
{% macro bps_of(amount, bps, mode) -%}
    {{ round_div('(cast((' ~ amount ~ ') as hugeint) * (' ~ bps ~ '))', '10000', mode) }}
{%- endmacro %}

{#- A decimal(18, 6) rate as an integer number of millionths. -#}
{% macro micros(rate) -%}
    cast({{ rate }} * 1000000 as bigint)
{%- endmacro %}

{#- numerator ÷ denominator in basis points, exact to 0.0001 bp (half up), as DECIMAL; null when the denominator is
    0 or null. A rate, not money. -#}
{% macro rate_bps(numerator, denominator) -%}
    (
        cast({{ round_half_up('cast(' ~ numerator ~ ' as hugeint) * 100000000', 'nullif(' ~ denominator ~ ', 0)') }}
            as decimal(18, 0))
        * cast(0.0001 as decimal(5, 4))
    )
{%- endmacro %}
