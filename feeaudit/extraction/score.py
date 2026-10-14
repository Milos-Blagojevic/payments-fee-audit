"""Score extracted contracts (contracts/extracted/*.yml) field by field against the ground truth (contracts/providers/).

One row per field: every header field and every leaf parameter of every term, terms matched by clause id. A field
is correct when its extracted value equals the expected value exactly (same JSON value and type). Free text
(`title`), the redundant `component` and the review flag `approved` are not scored. Expected fields the extraction
lacks are wrong; extracted fields or clauses the ground truth lacks are wrong too. Versions without an extracted
file are reported as not run. Reads only committed files, so it is deterministic and safe in CI.
"""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import duckdb
import yaml

IGNORED_TERM_KEYS = {"clause", "title", "component", "approved"}


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _leaves(value, path):
    """{path: leaf value} of a nested dict/list value."""
    if isinstance(value, dict) and value:
        out = {}
        for key, sub in value.items():
            out.update(_leaves(sub, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(value, list) and value:
        out = {}
        for i, sub in enumerate(value):
            out.update(_leaves(sub, f"{path}[{i}]"))
        return out
    return {path: value}


def _term_leaves(term, prefix):
    return _leaves({k: v for k, v in term.items() if k not in IGNORED_TERM_KEYS}, prefix)


def _fields(doc):
    """{field path: value} for a contract version; extra or duplicate clauses keep distinct paths."""
    header = _leaves({k: v for k, v in doc.items() if k != "terms"}, "")
    terms = {}
    for term in doc.get("terms") or []:
        if not isinstance(term, dict):
            continue
        clause = term.get("clause")
        prefix = f"terms[{clause}]"
        while prefix in terms:
            prefix += "(duplicate)"
        terms[prefix] = _term_leaves(term, prefix)
    return header, terms


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def compare(expected, extracted):
    """[(field path, expected JSON or None, extracted JSON or None, correct)] for one contract version."""
    exp_header, exp_terms = _fields(expected)
    ext_header, ext_terms = _fields(extracted)
    exp = dict(exp_header)
    for leaves in exp_terms.values():
        exp.update(leaves)
    ext = dict(ext_header)
    for leaves in ext_terms.values():
        ext.update(leaves)
    rows = []
    for path, value in exp.items():
        got = _json(ext[path]) if path in ext else None
        rows.append((path, _json(value), got, got == _json(value)))
    rows += [(path, None, _json(value), False) for path, value in ext.items() if path not in exp]
    return rows


def _read(path):
    try:
        doc = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError:
        return {}
    return _plain(doc) if isinstance(doc, dict) else {}


def score(providers_dir="contracts/providers", extracted_dir="contracts/extracted"):
    """(rows, versions): rows (contract, version, field_path, expected, extracted, correct) for every scored
    version; versions [{name, contract, version, status, correct, total}] for every ground-truth version."""
    rows, versions = [], []
    for truth_path in sorted(Path(providers_dir).glob("*.yml")):
        expected = _plain(yaml.safe_load(truth_path.read_text()))
        entry = {"name": truth_path.stem, "contract": expected["contract_id"], "version": expected["version"]}
        extracted_path = Path(extracted_dir) / truth_path.name
        if not extracted_path.exists():
            versions.append({**entry, "status": "not run", "correct": 0, "total": 0})
            continue
        compared = compare(expected, _read(extracted_path))
        rows += [(entry["contract"], entry["version"], *row) for row in compared]
        correct = sum(1 for row in compared if row[3])
        versions.append({**entry, "status": "scored", "correct": correct, "total": len(compared)})
    return rows, versions


def write_scores(rows, db_path="warehouse/fees.duckdb"):
    """(Re)create evaluation.extraction_scores."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS evaluation")
        con.execute(
            "CREATE OR REPLACE TABLE evaluation.extraction_scores (contract VARCHAR, version INTEGER, "
            "field_path VARCHAR, expected VARCHAR, extracted VARCHAR, correct BOOLEAN)"
        )
        if rows:
            con.executemany("INSERT INTO evaluation.extraction_scores VALUES (?, ?, ?, ?, ?, ?)", rows)


def accuracy(correct, total):
    """Percentage with one decimal, as a string."""
    return f"{(Decimal(100 * correct) / total).quantize(Decimal('0.1'))}%" if total else "n/a"


def report(versions):
    """Lines printed by the CLI: accuracy per contract version, per contract and overall."""
    lines = []
    width = max((len(v["name"]) for v in versions), default=0)
    for v in versions:
        label = f"{v['name']:<{width}}  {v['contract']} v{v['version']}"
        if v["status"] == "not run":
            lines.append(f"{label}  not run (no extracted file)")
        else:
            lines.append(f"{label}  {v['correct']}/{v['total']} fields correct  {accuracy(v['correct'], v['total'])}")
    scored = [v for v in versions if v["status"] == "scored"]
    by_contract = {}
    for v in scored:
        c = by_contract.setdefault(v["contract"], [0, 0])
        c[0] += v["correct"]
        c[1] += v["total"]
    if by_contract:
        lines.append("")
    for contract, (correct, total) in sorted(by_contract.items()):
        lines.append(f"{contract}  {correct}/{total} fields correct  {accuracy(correct, total)}")
    correct = sum(v["correct"] for v in scored)
    total = sum(v["total"] for v in scored)
    lines.append("")
    lines.append(
        f"overall  {correct}/{total} fields correct  {accuracy(correct, total)}  "
        f"({len(scored)} of {len(versions)} contract versions scored)"
    )
    return lines
