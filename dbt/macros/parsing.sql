{#- Parsing and normalisation helpers used by the staging models only. -#}

{#- Amount in major units ("12.34", "12,34", " -0.05") to integer minor units; exact decimal, no float. -#}
{% macro major_to_minor(column) -%}
    cast(cast(replace(trim({{ column }}), ',', '.') as decimal(18, 2)) * 100 as bigint)
{%- endmacro %}

{#- Amount already in integer minor units. -#}
{% macro minor_to_bigint(column) -%}
    cast(trim({{ column }}) as bigint)
{%- endmacro %}

{#- ISO-8601 timestamp with an offset or `Z` to a naive UTC timestamp. -#}
{% macro utc_from_iso(column) -%}
    timezone('UTC', cast({{ column }} as timestamptz))
{%- endmacro %}

{#- Local wall-clock time without offset in the given IANA zone to a naive UTC timestamp. -#}
{% macro utc_from_local(column, zone) -%}
    timezone('UTC', timezone({{ zone }}, cast({{ column }} as timestamp)))
{%- endmacro %}

{#- Naive UTC timestamp to the wall-clock time of the given IANA zone (expression or column). -#}
{% macro local_from_utc(column, zone) -%}
    timezone({{ zone }}, timezone('UTC', {{ column }}))
{%- endmacro %}

{#- `YYYY-MM` to the first day of that month. -#}
{% macro month_start(column) -%}
    cast(strptime(trim({{ column }}) || '-01', '%Y-%m-%d') as date)
{%- endmacro %}

{#- Statement month from a file name ending in `_<YYYY-MM>.csv`. -#}
{% macro month_from_file_name(column) -%}
    {{ month_start("regexp_extract(" ~ column ~ ", '_(\\d{4}-\\d{2})\\.csv$', 1)") }}
{%- endmacro %}

{#- Export date from a file name ending in `_<YYYY-MM-DD>.csv`. -#}
{% macro date_from_file_name(column) -%}
    cast(regexp_extract({{ column }}, '_(\d{4}-\d{2}-\d{2})\.csv$', 1) as date)
{%- endmacro %}

{#- N05: currency codes in any case, with padding. -#}
{% macro normalize_currency(column) -%}
    upper(trim({{ column }}))
{%- endmacro %}

{#- N05: card scheme labels (`VISA `, `Visa`, `MC`, `MasterCard`, ...). Unknown labels pass through lower-cased
    so that the accepted_values tests catch them. -#}
{% macro normalize_card_scheme(column) -%}
    case lower(trim({{ column }}))
        when 'mc' then 'mastercard'
        else lower(trim({{ column }}))
    end
{%- endmacro %}

{#- N05: card type labels (`Consumer Debit`, `consumer-debit`, `debit`, `business`, ...). -#}
{% macro normalize_card_type(column) -%}
    case regexp_replace(lower(trim({{ column }})), '[ -]+', '_', 'g')
        when 'debit' then 'consumer_debit'
        when 'credit' then 'consumer_credit'
        when 'business' then 'commercial'
        else regexp_replace(lower(trim({{ column }})), '[ -]+', '_', 'g')
    end
{%- endmacro %}

{#- N05: card region labels (`INTRA_EEA`, `intra-eea`, ...). -#}
{% macro normalize_card_region(column) -%}
    regexp_replace(lower(trim({{ column }})), '[ -]+', '_', 'g')
{%- endmacro %}

{#- Card segment of data contract section 2. -#}
{% macro card_segment(card_type, card_region) -%}
    case
        when {{ card_type }} in ('consumer_debit', 'consumer_credit') and {{ card_region }} in ('domestic', 'intra_eea')
            then 'eea_consumer'
        when {{ card_type }} is null or {{ card_region }} is null then null
        else 'other'
    end
{%- endmacro %}
