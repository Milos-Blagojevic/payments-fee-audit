{#- Display helpers for the `formula` and `evidence` strings; integer arithmetic only. -#}

{#- Minor units as major units with thousands separators: 800000 -> '8,000.00', -5 -> '-0.05'. -#}
{% macro fmt_money(minor) -%}
    (
        case when cast({{ minor }} as hugeint) < 0 then '-' else '' end
        || format('{:,}', abs(cast({{ minor }} as hugeint)) // 100)
        || '.'
        || lpad(cast(abs(cast({{ minor }} as hugeint)) % 100 as varchar), 2, '0')
    )
{%- endmacro %}

{#- Basis points as a percentage: 32 -> '0.32%', 140 -> '1.40%'. -#}
{% macro fmt_bps(bps) -%}
    (cast({{ bps }} // 100 as varchar) || '.' || lpad(cast({{ bps }} % 100 as varchar), 2, '0') || '%')
{%- endmacro %}

{#- A contract reference: 'NG-2025-01 v2 §4.2'. -#}
{% macro fmt_clause(contract_id, contract_version, clause) -%}
    ({{ contract_id }} || ' v' || {{ contract_version }} || ' §' || {{ clause }})
{%- endmacro %}
