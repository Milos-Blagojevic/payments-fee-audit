{#-
    Versions of the same contract must be contiguous and non-overlapping: numbered 1, 2, ... in order of
    effective_from; each version ends (inclusive date) the day before the next one starts; only the last version
    is open-ended; no version ends before it starts.
-#}
{% test contiguous_versions(model, contract_column, version_column, from_column, to_column) %}
with ordered as (
    select
        {{ contract_column }} as contract_key,
        {{ version_column }} as version_no,
        {{ from_column }} as valid_from,
        {{ to_column }} as valid_to,
        row_number() over (partition by {{ contract_column }} order by {{ from_column }}) as position,
        lead({{ from_column }}) over (partition by {{ contract_column }} order by {{ from_column }}) as next_from
    from {{ model }}
)

select *
from ordered
where version_no is distinct from position
    or valid_from is null
    or (next_from is null and valid_to is not null)
    or (next_from is not null and valid_to is distinct from cast(next_from - interval 1 day as date))
    or valid_to < valid_from
{% endtest %}
