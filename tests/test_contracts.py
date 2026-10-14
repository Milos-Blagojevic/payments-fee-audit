from pathlib import Path

import duckdb
import pytest
import yaml

from feeaudit.contracts import ContractError, load_contract_file, load_contracts, main, write_contracts

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "contracts"
NORTHGATE_V1 = CONTRACTS / "providers" / "northgate-v1.yml"
NORTHGATE_V2 = CONTRACTS / "providers" / "northgate-v2.yml"


def _doc(path):
    return yaml.safe_load(path.read_text())


def _write(directory, name, doc):
    path = directory / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def _term(doc, kind):
    return next(t for t in doc["terms"] if t["kind"] == kind)


@pytest.mark.parametrize("path", sorted(CONTRACTS.rglob("*.yml")), ids=lambda p: p.name)
def test_committed_file_validates(path):
    assert load_contract_file(path)["terms"]


def test_committed_contracts_load_together():
    assert load_contracts(CONTRACTS)


def test_bad_kind_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    doc["terms"][0]["kind"] = "surcharge"
    with pytest.raises(ContractError, match=r"terms\[0\]\.kind"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_missing_markup_tiers_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    del _term(doc, "markup_bps_tiered")["tiers"]
    with pytest.raises(ContractError, match="'tiers' is a required property"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_payout_fee_without_price_rejected(tmp_path):
    doc = _doc(CONTRACTS / "providers" / "kestrel-v1.yml")
    del doc["terms"][0]["fixed_minor"]
    with pytest.raises(ContractError, match=r"kestrel|c\.yml"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_payout_fee_with_partial_bps_rejected(tmp_path):
    doc = _doc(CONTRACTS / "providers" / "kestrel-v1.yml")
    del doc["terms"][2]["cap_minor"]
    with pytest.raises(ContractError, match=r"terms\[2\]"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_wrong_component_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    _term(doc, "markup_bps_tiered")["component"] = "fixed_fee"
    with pytest.raises(ContractError, match="component"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_provider_kind_under_client_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    doc["party"] = "client"
    with pytest.raises(ContractError, match=r"terms\[0\]\.kind"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_tiers_not_increasing_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    _term(doc, "markup_bps_tiered")["tiers"][1]["up_to_minor"] = 100
    with pytest.raises(ContractError, match="strictly increasing"):
        load_contract_file(_write(tmp_path, "c.yml", doc))


def test_duplicate_clause_and_bad_timezone_rejected(tmp_path):
    doc = _doc(NORTHGATE_V1)
    doc["timezone"] = "Mars/Olympus"
    doc["terms"][1]["clause"] = doc["terms"][0]["clause"]
    with pytest.raises(ContractError) as exc:
        load_contract_file(_write(tmp_path, "c.yml", doc))
    assert "duplicate clause" in str(exc.value) and "timezone" in str(exc.value)


def _two_versions(tmp_path, v2_from, v1_to=None):
    v1, v2 = _doc(NORTHGATE_V1), _doc(NORTHGATE_V2)
    if v1_to:
        v1["effective_to"] = v1_to
    v2["effective_from"] = v2_from
    _write(tmp_path, "v1.yml", v1)
    _write(tmp_path, "v2.yml", v2)
    return load_contracts(tmp_path)


@pytest.mark.parametrize("v2_from", ["2025-07-01", "2025-06-01"])
def test_non_increasing_effective_from_rejected(tmp_path, v2_from):
    with pytest.raises(ContractError, match="NG-2025-01.*effective_from"):
        _two_versions(tmp_path, v2_from)


def test_effective_to_overlapping_next_version_rejected(tmp_path):
    with pytest.raises(ContractError, match="NG-2025-01.*effective_to 2026-04-15"):
        _two_versions(tmp_path, "2026-04-01", v1_to="2026-04-15")


def test_matching_effective_to_accepted(tmp_path):
    contracts = _two_versions(tmp_path, "2026-04-01", v1_to="2026-03-31")
    assert contracts[0]["effective_to"] == "2026-03-31"


def test_duplicate_version_rejected(tmp_path):
    _write(tmp_path, "a.yml", _doc(NORTHGATE_V1))
    _write(tmp_path, "b.yml", _doc(NORTHGATE_V1))
    with pytest.raises(ContractError, match="NG-2025-01: versions"):
        load_contracts(tmp_path)


def test_derived_effective_to():
    northgate = {c["version"]: c for c in load_contracts(CONTRACTS) if c["contract_id"] == "NG-2025-01"}
    assert northgate[1]["effective_to"] == "2026-03-31"
    assert northgate[2]["effective_to"] is None
    assert northgate[1]["source_file"].endswith("contracts/providers/northgate-v1.yml")


def test_write_contracts_round_trip(tmp_path):
    contracts = load_contracts(CONTRACTS / "providers")
    db = tmp_path / "fees.duckdb"
    write_contracts(contracts, db)
    with duckdb.connect(str(db)) as con:
        n_versions = con.execute("SELECT count(*) FROM contracts.contract_versions").fetchone()[0]
        n_terms = con.execute("SELECT count(*) FROM contracts.contract_terms").fetchone()[0]
        effective_to = con.execute(
            "SELECT effective_to FROM contracts.contract_versions WHERE contract_id = 'NG-2025-01' AND version = 1"
        ).fetchone()[0]
        swift = con.execute(
            "SELECT bps, min_minor, cap_minor, fixed_minor, rail FROM contracts.contract_terms "
            "WHERE contract_id = 'KP-2025-09' AND version = 1 AND clause = '2.3'"
        ).fetchone()
        components, refund_fee, credit = con.execute(
            "SELECT components, fee_minor, credit_original_markup FROM contracts.contract_terms "
            "WHERE contract_id = 'NG-2025-01' AND version = 1 AND kind = 'refund'"
        ).fetchone()
        pass_through = con.execute(
            "SELECT components, parameters->>'reference' FROM contracts.contract_terms "
            "WHERE contract_id = 'NG-2025-01' AND version = 1 AND kind = 'pass_through'"
        ).fetchone()
    assert n_versions == len(contracts)
    assert n_terms == sum(len(c["terms"]) for c in contracts)
    assert str(effective_to) == "2026-03-31"
    assert swift == (10, 800, 4000, None, "swift")
    assert components == ["refund_fee", "markup_credit"] and refund_fee == 10 and credit is True
    assert pass_through == (["interchange", "scheme_fee"], "interchange_table_v1")


def test_main_fails_on_bad_file(tmp_path, capsys):
    doc = _doc(NORTHGATE_V1)
    doc["rounding"]["mode"] = "banker"
    _write(tmp_path, "bad.yml", doc)
    assert main(["--contracts-dir", str(tmp_path), "--db", str(tmp_path / "x.duckdb")]) == 1
    err = capsys.readouterr().err
    assert "bad.yml" in err and "$.rounding.mode" in err
    assert not (tmp_path / "x.duckdb").exists()


def test_main_loads_committed_contracts(tmp_path, capsys):
    assert main(["--contracts-dir", str(CONTRACTS), "--db", str(tmp_path / "f.duckdb")]) == 0
    assert "files" in capsys.readouterr().out
