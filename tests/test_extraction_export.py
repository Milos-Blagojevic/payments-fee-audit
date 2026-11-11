"""Data of the site's extraction page (feeaudit/extraction/export.py): the committed file equals a fresh export, and it
carries exactly what `build_request` sends for each sample."""

import json
from pathlib import Path

import pytest

from feeaudit.extraction.budget import load_config
from feeaudit.extraction.export import EXPORT_PATH, render_export
from feeaudit.extraction.extract import build_request

REPO = Path(__file__).resolve().parents[1]
EXPORT = json.loads((REPO / EXPORT_PATH).read_text())


def test_committed_export_equals_fresh_export():
    assert (REPO / EXPORT_PATH).read_text() == render_export(REPO)


@pytest.mark.parametrize("sample", EXPORT["samples"], ids=lambda s: s["name"])
def test_export_carries_the_request_build_request_sends(sample):
    config = load_config(REPO / "config/llm.yml")
    request = build_request(sample["name"], EXPORT["model"], config, REPO / "contracts/text")
    assert request["system"] == EXPORT["system"]
    assert request["messages"] == sample["messages"]
    assert request["output_config"] == {"effort": EXPORT["effort"], "format": {"type": "json_schema",
                                                                              "schema": EXPORT["extraction_schema"]}}
    assert request["max_tokens"] == EXPORT["max_tokens"]
