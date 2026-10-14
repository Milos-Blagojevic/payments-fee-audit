"""Load, validate and store the fee contracts (docs/data-contract.md section 4)."""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb
import yaml
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).with_name("contract_schema.json")

# Components of each kind; a term's optional `component` must equal the single one.
KIND_COMPONENTS = {
    "pass_through": ["interchange", "scheme_fee"],
    "markup_bps_tiered": ["markup"],
    "per_transaction_fixed": ["fixed_fee"],
    "blended_rate": ["transaction_fee"],
    "volume_discount": ["volume_adjustment"],
    "refund": ["refund_fee", "markup_credit"],
    "chargeback_fee": ["chargeback_fee"],
    "monthly_minimum": ["monthly_minimum"],
    "payout_fee": ["payout_fee"],
    "fx_spread_cap": ["fx_conversion"],
    "payment_fee_by_segment": ["payment_fees"],
    "fx_markup": ["fx_markup"],
    "platform_fee": ["platform_fee"],
    "volume_discount_tiered": ["volume_discount"],
    "promo_discount": ["promo_discount"],
}

TERM_COLUMNS = {
    "amount_minor": "BIGINT",
    "fee_minor": "BIGINT",
    "fixed_minor": "BIGINT",
    "bps": "INTEGER",
    "min_minor": "BIGINT",
    "cap_minor": "BIGINT",
    "rail": "VARCHAR",
    "segment": "VARCHAR",
    "basis": "VARCHAR",
    "tiering": "VARCHAR",
    "reference": "VARCHAR",
    "applies_to": "VARCHAR",
    "credit_original_markup": "BOOLEAN",
    "discount_pct": "INTEGER",
    "valid_until": "DATE",
}

_validator = None


class ContractError(Exception):
    """A contract file or set of contract versions is invalid."""


def _get_validator():
    global _validator
    if _validator is None:
        schema = json.loads(SCHEMA_PATH.read_text())
        _validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return _validator


def _dates_to_iso(value):
    if isinstance(value, dict):
        return {k: _dates_to_iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_iso(v) for v in value]
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _rel(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _python_checks(doc):
    """Checks the schema cannot express; returns (json_path, message) pairs."""
    problems = []
    try:
        ZoneInfo(doc["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(("$.timezone", f"unknown timezone {doc['timezone']!r}"))
    if doc.get("effective_to") and doc["effective_to"] < doc["effective_from"]:
        problems.append(("$.effective_to", "effective_to is before effective_from"))
    seen = set()
    for i, term in enumerate(doc["terms"]):
        if term["clause"] in seen:
            problems.append((f"$.terms[{i}].clause", f"duplicate clause {term['clause']!r}"))
        seen.add(term["clause"])
        tiers = term.get("tiers")
        if not tiers:
            continue
        bounds = [t["up_to_minor"] for t in tiers]
        if bounds[-1] is not None:
            problems.append((f"$.terms[{i}].tiers[{len(tiers) - 1}].up_to_minor", "last tier must have up_to_minor null"))
        for j, bound in enumerate(bounds[:-1]):
            if bound is None:
                problems.append((f"$.terms[{i}].tiers[{j}].up_to_minor", "only the last tier may have up_to_minor null"))
            elif j > 0 and bounds[j - 1] is not None and bound <= bounds[j - 1]:
                problems.append((f"$.terms[{i}].tiers[{j}].up_to_minor", "up_to_minor must be strictly increasing"))
    return problems


def load_contract_file(path):
    """Read one contract YAML, validate it and return it with dates as ISO strings."""
    path = Path(path)
    try:
        doc = _dates_to_iso(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"{_rel(path)}: cannot read: {exc}") from None
    errors = sorted(_get_validator().iter_errors(doc), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    problems = [(e.json_path, e.message) for e in errors]
    if not problems:
        problems = _python_checks(doc)
    if problems:
        raise ContractError("\n".join(f"{_rel(path)}: {p}: {m}" for p, m in problems))
    return doc


def _version_checks(contract_id, versions):
    problems = []
    files = ", ".join(v["source_file"] for v in versions)
    for key in ("party", "counterparty"):
        values = sorted({v[key] for v in versions})
        if len(values) > 1:
            problems.append(f"{contract_id}: {key} differs between versions ({', '.join(values)}) in {files}")
    numbers = [v["version"] for v in versions]
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        problems.append(f"{contract_id}: versions must be unique and exactly 1..n, got {sorted(numbers)} in {files}")
        return problems
    for prev, nxt in zip(versions, versions[1:]):
        if nxt["effective_from"] <= prev["effective_from"]:
            problems.append(
                f"{contract_id}: version {nxt['version']} ({nxt['source_file']}) effective_from {nxt['effective_from']} "
                f"is not after version {prev['version']} ({prev['source_file']}) effective_from {prev['effective_from']}"
            )
            continue
        expected_to = (dt.date.fromisoformat(nxt["effective_from"]) - dt.timedelta(days=1)).isoformat()
        stated = prev.get("effective_to")
        if stated is not None and stated != expected_to:
            problems.append(
                f"{contract_id}: version {prev['version']} ({prev['source_file']}) effective_to {stated} "
                f"must be {expected_to}, the day before version {nxt['version']} ({nxt['source_file']}) starts"
            )
        prev["effective_to"] = expected_to
    return problems


def load_contracts(contracts_dir="contracts"):
    """Load and validate every `*.yml` under contracts_dir; add `source_file` and derived `effective_to`."""
    paths = sorted(Path(contracts_dir).rglob("*.yml"))
    problems, contracts = [], []
    for path in paths:
        try:
            doc = load_contract_file(path)
        except ContractError as exc:
            problems.append(str(exc))
            continue
        doc["source_file"] = _rel(path)
        contracts.append(doc)
    by_id = {}
    for doc in contracts:
        by_id.setdefault(doc["contract_id"], []).append(doc)
    for contract_id, versions in sorted(by_id.items()):
        versions.sort(key=lambda v: v["version"])
        problems.extend(_version_checks(contract_id, versions))
        versions[-1].setdefault("effective_to", None)
    if problems:
        raise ContractError("\n".join(problems))
    return sorted(contracts, key=lambda d: (d["contract_id"], d["version"]))


def term_components(term):
    """Fee components a term produces."""
    if term["kind"] == "payout_fee_by_rail":
        return [f"payout_fees_{rail}" for rail in term["rails"]]
    return KIND_COMPONENTS[term["kind"]]


def write_contracts(contracts, db_path="warehouse/fees.duckdb"):
    """(Re)create schema `contracts` with tables contract_versions and contract_terms."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    typed = ", ".join(f"{name} {sql_type}" for name, sql_type in TERM_COLUMNS.items())
    version_rows, term_rows = [], []
    for c in contracts:
        version_rows.append((
            c["contract_id"], c["party"], c["counterparty"], c["name"], c["version"], c["effective_from"],
            c.get("effective_to"), c["currency"], c["timezone"], c["rounding"]["mode"], c["rounding"]["level"],
            c["dispute_window_days"], c["source_file"],
        ))
        for t in c["terms"]:
            params = {k: v for k, v in t.items() if k not in ("clause", "kind", "title", "component", "components")}
            term_rows.append((
                c["contract_id"], c["version"], t["clause"], t["kind"], t["title"], term_components(t),
                json.dumps(params), *(t.get(name) for name in TERM_COLUMNS),
            ))
    with duckdb.connect(str(db_path)) as con:
        con.execute("DROP SCHEMA IF EXISTS contracts CASCADE")
        con.execute("CREATE SCHEMA contracts")
        con.execute(
            "CREATE TABLE contracts.contract_versions (contract_id VARCHAR, party VARCHAR, counterparty VARCHAR, "
            "name VARCHAR, version INTEGER, effective_from DATE, effective_to DATE, currency VARCHAR, timezone VARCHAR, "
            "rounding_mode VARCHAR, rounding_level VARCHAR, dispute_window_days INTEGER, source_file VARCHAR)"
        )
        con.execute(
            "CREATE TABLE contracts.contract_terms (contract_id VARCHAR, version INTEGER, clause VARCHAR, kind VARCHAR, "
            f"title VARCHAR, components VARCHAR[], parameters JSON, {typed})"
        )
        if version_rows:
            con.executemany(f"INSERT INTO contracts.contract_versions VALUES ({', '.join(['?'] * 13)})", version_rows)
        if term_rows:
            con.executemany(
                f"INSERT INTO contracts.contract_terms VALUES ({', '.join(['?'] * (7 + len(TERM_COLUMNS)))})", term_rows
            )


def main(argv=None):
    """CLI: validate every contract and load it into DuckDB; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-dir", default="contracts")
    parser.add_argument("--db", default="warehouse/fees.duckdb")
    args = parser.parse_args(argv)
    try:
        contracts = load_contracts(args.contracts_dir)
    except ContractError as exc:
        print(f"contract validation failed:\n{exc}", file=sys.stderr)
        return 1
    write_contracts(contracts, args.db)
    files = len(contracts)
    ids = len({c["contract_id"] for c in contracts})
    terms = sum(len(c["terms"]) for c in contracts)
    print(f"{files} files, {ids} contracts, {terms} terms loaded into {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
