-- Findings raised on planted noise rows and rounding findings outside the rounding noise class
-- (evaluation.noise_false_positives), plus findings no truth row explains (evaluation.unexplained_findings).
-- One row per category, also when the count is zero.
with categories(category, label, sort) as (
    values
        ('noise', 'Findings on noise rows (false positives)', 1),
        ('rounding_off_n08', 'Rounding findings outside the rounding noise class', 2),
        ('unexplained', 'Findings no planted error or noise row explains', 3)
),
counts as (
    select category, count(distinct finding_id) as findings, sum(difference_minor)::bigint as difference_minor
    from evaluation.noise_false_positives
    group by all
    union all
    select 'unexplained', count(*), sum(difference_minor)::bigint
    from evaluation.unexplained_findings
)
select c.category, c.label, c.sort, coalesce(n.findings, 0) as findings, coalesce(n.difference_minor, 0) as difference_minor
from categories c
left join counts n using (category)
order by c.sort
