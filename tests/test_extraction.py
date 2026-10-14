"""LLM extraction (feeaudit/extraction): a fake Anthropic client, the budget guard, the approval flag and scoring."""

import dataclasses
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
import yaml
from jsonschema import Draft202012Validator

from feeaudit.contracts import ContractError, load_contract_file
from feeaudit.extraction.__main__ import main
from feeaudit.extraction.budget import BudgetError, call_cost, load_config
from feeaudit.extraction.extract import ExtractionError, build_request, extract, extraction_schema, prompt_sha256
from feeaudit.extraction.score import compare, score

REPO = Path(__file__).resolve().parents[1]
PROVIDERS = REPO / "contracts/providers"
TEXT = REPO / "contracts/text"
NOW = dt.datetime(2026, 10, 14, 12, 0, tzinfo=dt.timezone.utc)


class FakeResponse:
    def __init__(self, text, usage, stop_reason, model):
        self.content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
        self.usage = SimpleNamespace(cache_creation_input_tokens=None, cache_read_input_tokens=0, **usage)
        self.stop_reason = stop_reason
        self.model = model

    def model_dump(self, mode):
        assert mode == "json"
        return {
            "model": self.model, "stop_reason": self.stop_reason, "usage": vars(self.usage),
            "content": [vars(block) for block in self.content],
        }


class FakeMessages:
    """Stands in for `anthropic.Anthropic().messages`; records every call, never touches the network."""

    def __init__(self, text, counted=5000, input_tokens=5000, output_tokens=3000, stop_reason="end_turn"):
        self.text, self.counted, self.stop_reason = text, counted, stop_reason
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        self.created, self.counted_calls = [], []

    def count_tokens(self, **kwargs):
        self.counted_calls.append(kwargs)
        return SimpleNamespace(input_tokens=self.counted)

    def create(self, **kwargs):
        self.created.append(kwargs)
        return FakeResponse(self.text, self.usage, self.stop_reason, kwargs["model"])


def _client(doc=None, **kwargs):
    text = json.dumps(doc if doc is not None else _truth("northgate-v2"))
    return SimpleNamespace(messages=FakeMessages(text, **kwargs))


def _truth(name):
    doc = load_contract_file(PROVIDERS / f"{name}.yml")
    for term in doc["terms"]:
        term.pop("component", None)
    return doc


@pytest.fixture
def config(monkeypatch):
    monkeypatch.delenv("FEEAUDIT_LLM_MODEL", raising=False)
    return dataclasses.replace(load_config(REPO / "config/llm.yml"), prices_verified=True)


def _ledger(out_dir, *costs):
    path = out_dir / "recorded/spend.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    calls = [{"name": "earlier", "cost_usd": c} for c in costs]
    path.write_text(json.dumps({"total_usd": str(sum(map(Decimal, costs), Decimal(0))), "calls": calls}))
    return path


# ---- extraction -------------------------------------------------------------

def test_extract_writes_unapproved_terms_and_records_usage_and_cost(tmp_path, config):
    client = _client()
    result = extract("northgate-v2", client, config, TEXT, tmp_path, now=NOW)

    request = client.messages.created[0]
    assert request["model"] == "claude-opus-5-5" and "tool_choice" not in request
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": extraction_schema()}
    content = request["messages"][0]["content"]
    assert '<document role="master_agreement">' in content and '<document role="amendment_letter">' in content
    assert (TEXT / "northgate-v1.md").read_text() in content and (TEXT / "northgate-v2.md").read_text() in content
    assert "max_tokens" not in client.messages.counted_calls[0]

    out = (tmp_path / "northgate-v2.yml").read_text()
    assert out.startswith("# Extracted by claude-opus-5-5 from contracts/text/northgate-v1.md")
    doc = yaml.safe_load(out)
    assert doc["terms"] and all(term["approved"] is False for term in doc["terms"])
    assert result["validation_errors"] == []
    with pytest.raises(ContractError, match=r"northgate-v2\.yml: \$\.terms\[0\]: clause 3\.1 is not approved"):
        load_contract_file(tmp_path / "northgate-v2.yml")

    # 5,000 input tokens at USD 4/M + 3,000 output tokens at USD 20/M
    assert result["cost_usd"] == Decimal("0.08")
    recorded = json.loads((tmp_path / "recorded/northgate-v2.json").read_text())
    assert recorded["model"] == "claude-opus-5-5" and recorded["timestamp"] == "2026-10-14T12:00:00Z"
    assert recorded["usage"] == {"input_tokens": 5000, "output_tokens": 3000, "cache_creation_input_tokens": 0,
                                 "cache_read_input_tokens": 0}
    assert recorded["cost_usd"] == "0.08" and recorded["prompt_sha256"] == prompt_sha256(request)
    assert recorded["request"] == json.loads(json.dumps(request)) and recorded["response"]["stop_reason"] == "end_turn"
    assert sorted(recorded["sources"]) == ["contracts/text/northgate-v1.md", "contracts/text/northgate-v2.md"]
    assert recorded["estimate"] == {"input_tokens": 5000, "max_output_tokens": 16000, "cost_usd": "0.34"}

    extract("kestrel-v1", _client(_truth("kestrel-v1")), config, TEXT, tmp_path, now=NOW)
    ledger = json.loads((tmp_path / "recorded/spend.json").read_text())
    assert [c["name"] for c in ledger["calls"]] == ["northgate-v2", "kestrel-v1"]
    assert ledger["total_usd"] == "0.16"


def test_request_is_deterministic_and_master_only_for_version_1(config):
    a = build_request("kestrel-v1", "claude-opus-5-5", config, TEXT)
    assert prompt_sha256(a) == prompt_sha256(build_request("kestrel-v1", "claude-opus-5-5", config, TEXT))
    assert a["messages"][0]["content"].count("<document ") == 1


def test_budget_guard_refuses_a_call_that_could_exceed_the_cap(tmp_path, config):
    ledger = _ledger(tmp_path, "4.5", "0.3")
    before = ledger.read_text()
    client = _client(counted=5000)
    # worst case: 4.80 spent + 5,000 × 4/M + 16,000 × 20/M = 4.80 + 0.34 = 5.14 > 5.00
    with pytest.raises(BudgetError, match="would exceed the budget of USD 5"):
        extract("northgate-v2", client, config, TEXT, tmp_path, now=NOW)
    assert client.messages.created == [] and ledger.read_text() == before
    assert not (tmp_path / "northgate-v2.yml").exists()


def test_budget_guard_allows_a_call_within_the_cap(tmp_path, config):
    _ledger(tmp_path, "4.66")  # 4.66 + 0.34 = 5.00: allowed
    client = _client()
    extract("northgate-v2", client, config, TEXT, tmp_path, now=NOW)
    assert len(client.messages.created) == 1
    assert json.loads((tmp_path / "recorded/spend.json").read_text())["total_usd"] == "4.74"


def test_unverified_prices_refuse_before_any_call(tmp_path, config):
    client = _client()
    with pytest.raises(BudgetError, match="prices_verified is false"):
        extract("northgate-v2", client, dataclasses.replace(config, prices_verified=False), TEXT, tmp_path)
    assert client.messages.counted_calls == [] and client.messages.created == []


def test_model_from_env_needs_prices(tmp_path, config, monkeypatch):
    monkeypatch.setenv("FEEAUDIT_LLM_MODEL", "claude-unpriced")
    client = _client()
    with pytest.raises(BudgetError, match="no prices for model 'claude-unpriced'"):
        extract("northgate-v2", client, config, TEXT, tmp_path)
    assert client.messages.counted_calls == []


def test_unusable_response_is_recorded_and_paid(tmp_path, config):
    client = _client(stop_reason="max_tokens")
    with pytest.raises(ExtractionError, match="stop_reason 'max_tokens'"):
        extract("northgate-v1", client, config, TEXT, tmp_path, now=NOW)
    assert json.loads((tmp_path / "recorded/northgate-v1.json").read_text())["error"].startswith("stop_reason")
    assert json.loads((tmp_path / "recorded/spend.json").read_text())["total_usd"] == "0.08"
    assert not (tmp_path / "northgate-v1.yml").exists()


def test_cli_extract_refuses_with_committed_config(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("FEEAUDIT_LLM_MODEL", raising=False)
    args = ["extract", "--only", "northgate-v1", "--config", str(REPO / "config/llm.yml"), "--text-dir", str(TEXT),
            "--out-dir", str(tmp_path)]
    assert main(args) == 1
    assert "prices_verified is false" in capsys.readouterr().err


def test_cost_is_exact():
    prices = {"input": Decimal("4.00"), "output": Decimal("20.00"), "cache_write": Decimal("5"), "cache_read": Decimal("0.20")}
    assert call_cost(prices, 1, 1, 1, 1) == Decimal("0.0000292")


# ---- request schema ---------------------------------------------------------

UNSUPPORTED = {"minimum", "maximum", "minLength", "maxLength", "maxItems", "minProperties", "prefixItems",
               "propertyNames", "oneOf", "not", "if", "then", "$ref"}


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_extraction_schema_uses_only_supported_keywords():
    schema = extraction_schema()
    for node in _walk(schema):
        assert not UNSUPPORTED & set(node), node
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, node
        assert node.get("minItems", 0) <= 1


@pytest.mark.parametrize("path", sorted(PROVIDERS.glob("*.yml")), ids=lambda p: p.stem)
def test_ground_truth_fits_the_extraction_schema(path):
    validator = Draft202012Validator(extraction_schema())
    assert [e.message for e in validator.iter_errors(_truth(path.stem))] == []


# ---- scoring ----------------------------------------------------------------

def _hand_made_northgate_v2():
    """Ground truth with known errors: a stale tier rate, a wrong dispute window, clause 7.4 missing and an
    invented clause 9.9; titles reworded and approved flags added (neither is scored)."""
    doc = _truth("northgate-v2")
    doc["dispute_window_days"] = 30
    terms = [t for t in doc["terms"] if t["clause"] != "7.4"]
    next(t for t in terms if t["clause"] == "4.2")["tiers"][1]["bps"] = 35
    terms.append({"clause": "9.9", "kind": "chargeback_fee", "title": "Invented", "amount_minor": 100})
    for term in terms:
        term["title"] = "reworded"
        term["approved"] = False
    doc["terms"] = terms
    return doc


def _write_extracted(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "northgate-v2.yml").write_text(yaml.safe_dump(_hand_made_northgate_v2(), sort_keys=False))
    perfect = _truth("kestrel-v1")
    for term in perfect["terms"]:
        term["approved"] = False
    (directory / "kestrel-v1.yml").write_text(yaml.safe_dump(perfect, sort_keys=False))


def test_compare_finds_each_known_error():
    rows = compare(_truth("northgate-v2"), _hand_made_northgate_v2())
    wrong = {path: (expected, extracted) for path, expected, extracted, correct in rows if not correct}
    assert wrong == {
        "dispute_window_days": ("60", "30"),
        "terms[4.2].tiers[1].bps": ("32", "35"),
        "terms[7.4].kind": ('"monthly_minimum"', None),
        "terms[7.4].applies_to": ('"markup"', None),
        "terms[7.4].amount_minor": ("250000", None),
        "terms[9.9].kind": (None, '"chargeback_fee"'),
        "terms[9.9].amount_minor": (None, "100"),
    }
    # 11 header fields + 23 term fields expected, plus 2 invented ones
    assert len(rows) == 36 and sum(row[3] for row in rows) == 29


def test_score_exact_accuracy_and_not_run(tmp_path):
    _write_extracted(tmp_path / "extracted")
    rows, versions = score(PROVIDERS, tmp_path / "extracted")
    by_name = {v["name"]: v for v in versions}
    assert (by_name["northgate-v2"]["correct"], by_name["northgate-v2"]["total"]) == (29, 36)
    assert (by_name["kestrel-v1"]["correct"], by_name["kestrel-v1"]["total"]) == (29, 29)
    assert [v["name"] for v in versions if v["status"] == "not run"] == ["brightpay-v1", "kestrel-v2", "northgate-v1"]
    assert len(rows) == 65


def test_score_cli_writes_table_and_prints_accuracy(tmp_path, capsys):
    _write_extracted(tmp_path / "extracted")
    db = tmp_path / "fees.duckdb"
    assert main(["score", "--providers-dir", str(PROVIDERS), "--extracted-dir", str(tmp_path / "extracted"),
                 "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "northgate-v2  NG-2025-01 v2  29/36 fields correct  80.6%" in out
    assert "kestrel-v1    KP-2025-09 v1  29/29 fields correct  100.0%" in out
    assert "brightpay-v1  BP-2025-07 v1  not run" in out
    assert "overall  58/65 fields correct  89.2%  (2 of 5 contract versions scored)" in out
    with duckdb.connect(str(db), read_only=True) as con:
        total, correct = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE correct) FROM evaluation.extraction_scores"
        ).fetchone()
        row = con.execute(
            "SELECT contract, version, expected, extracted, correct FROM evaluation.extraction_scores "
            "WHERE field_path = 'terms[4.2].tiers[1].bps'"
        ).fetchone()
    assert (total, correct) == (65, 58)
    assert row == ("NG-2025-01", 2, "32", "35", False)


def test_score_without_extractions_exits_0(tmp_path, capsys):
    db = tmp_path / "fees.duckdb"
    assert main(["score", "--providers-dir", str(PROVIDERS), "--extracted-dir", str(tmp_path / "none"), "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert out.count("not run") == 5 and "(0 of 5 contract versions scored)" in out
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM evaluation.extraction_scores").fetchone()[0] == 0
