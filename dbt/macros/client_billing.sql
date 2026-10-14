{#- Client billing amounts are kept exact in 1 / exact_scale() minor units until the invoice line rounds them once
    (data contract section 1, `invoice_line` level). 10⁸ holds a basis-point fee (10⁻⁴) times a whole percentage
    discount (10⁻²) as an integer. -#}
{% macro exact_scale() -%}
    100000000
{%- endmacro %}
