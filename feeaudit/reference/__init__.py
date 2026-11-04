"""Python reference fee engine: expected provider charges from contracts and the raw ledger."""

from pathlib import Path

import duckdb

from feeaudit.reference.contracts import load_interchange, load_provider_contracts
from feeaudit.reference.engine import (
    ExpectedCharge,
    compute_expected_charges,
    read_ledger,
    write_expected_charges,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACTS = REPO_ROOT / "contracts" / "providers"
DEFAULT_INTERCHANGE = REPO_ROOT / "dbt" / "seeds" / "interchange_table_v1.csv"


def run(
    con: duckdb.DuckDBPyConnection,
    contracts_dir: Path = DEFAULT_CONTRACTS,
    interchange_csv: Path = DEFAULT_INTERCHANGE,
) -> list[ExpectedCharge]:
    """Read contracts and the raw ledger, compute expected charges, write `reference.expected_charges`."""
    contracts = load_provider_contracts(contracts_dir)
    interchange = load_interchange(interchange_csv)
    rows = compute_expected_charges(contracts, interchange, *read_ledger(con))
    write_expected_charges(con, rows)
    return rows


__all__ = ["ExpectedCharge", "compute_expected_charges", "read_ledger", "run", "write_expected_charges"]
