{#- The combination of the given columns is unique and has no nulls (a composite primary key). -#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as rows_with_key
from {{ model }}
group by all
having count(*) > 1 or {{ columns | join(' is null or ') }} is null
{% endtest %}
