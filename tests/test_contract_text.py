"""Contract prose (generator/contract_text.py): committed text equals a fresh render; amendments change only what changed."""

import re
from pathlib import Path

import pytest

from generator.contract_text import amount, rate, render_all, words
from feeaudit.contracts import load_contract_file

REPO = Path(__file__).resolve().parents[1]
PROVIDERS = REPO / "contracts/providers"
TEXT = REPO / "contracts/text"


def test_committed_text_equals_fresh_render():
    rendered = render_all(PROVIDERS)
    committed = {p.name: p.read_text() for p in TEXT.glob("*.md")}
    assert sorted(committed) == sorted(rendered) == sorted(f"{p.stem}.md" for p in PROVIDERS.glob("*.yml"))
    assert [name for name in rendered if committed[name] != rendered[name]] == []


def test_render_is_deterministic():
    assert render_all(PROVIDERS) == render_all(PROVIDERS)


@pytest.mark.parametrize("name", ["brightpay-v1", "kestrel-v1", "northgate-v1"])
def test_master_has_every_clause(name):
    text = (TEXT / f"{name}.md").read_text()
    doc = load_contract_file(PROVIDERS / f"{name}.yml")
    for term in doc["terms"]:
        assert re.search(rf"^\*\*{re.escape(term['clause'])} ", text, re.M), term["clause"]
    assert doc["contract_id"] in text and "Amendment" not in text.splitlines()[0]


def test_northgate_amendment_replaces_only_the_markup_clause():
    text = (TEXT / "northgate-v2.md").read_text()
    assert text.startswith("# Amendment No. 1 to the Master Acquiring Services Agreement")
    assert "dated 1 July 2025, reference NG-2025-01" in text and "take effect on 1 April 2026" in text
    assert re.findall(r"clause (\S+) is (?:deleted|inserted)", text) == ["4.2"]
    assert "0.32% (thirty-two basis points)" in text and "0.35%" not in text
    assert "subject to the monthly minimum in clause 7.4" in text


def test_kestrel_amendment_inserts_only_the_elixir_clause():
    text = (TEXT / "kestrel-v2.md").read_text()
    assert "the following new clause 2.4 is inserted after clause 2.3" in text
    assert re.findall(r"^> \*\*(\S+) ", text, re.M) == ["2.4"]
    assert "Elixir" in text and "EUR 0.30 (thirty euro cents)" in text
    assert "Payouts executed on or after that date" in text


def test_amounts_and_rates_as_written_in_contracts():
    assert words(1040) == "one thousand and forty"
    assert words(2_500_000) == "two million five hundred thousand"
    assert amount(250000) == "EUR 2,500.00 (two thousand five hundred euro)"
    assert amount(4) == "EUR 0.04 (four euro cents)"
    assert amount(250) == "EUR 2.50 (two euro and fifty cents)"
    assert rate(45) == "0.45% (forty-five basis points)"
    assert rate(140) == "1.40% (one hundred and forty basis points)"
    assert rate(1) == "0.01% (one basis point)"
