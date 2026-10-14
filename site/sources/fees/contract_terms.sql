-- Provider contract terms (main.dim_contract_terms), to show the clause behind a finding.
select
    contract_term_id,
    contract_id,
    contract_version,
    contract_id || ' v' || contract_version::varchar as contract,
    counterparty,
    clause,
    title,
    clause_text,
    strftime(effective_from, '%Y-%m-%d') as effective_from,
    coalesce(strftime(effective_to, '%Y-%m-%d'), 'current') as effective_to,
    dispute_window_days
from main.dim_contract_terms
where party = 'provider'
