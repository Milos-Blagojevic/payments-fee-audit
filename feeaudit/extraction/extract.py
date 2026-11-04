"""Extract one provider contract version from its prose (contracts/text/) with the Anthropic API.

The response is constrained by a JSON schema derived from feeaudit/contract_schema.json (structured outputs),
then validated against the full schema. Every extracted term gets `approved: false`, so the loader refuses the
file until a person has reviewed it. Every call is recorded with its usage and cost, and the spend ledger is
updated before anything else happens to the response.
"""

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import yaml

from feeaudit.contracts import SCHEMA_PATH, _rel, validate_contract
from feeaudit.extraction.budget import call_cost, check_budget, load_ledger, save_ledger, usd

TEXT_DIR = Path("contracts/text")
OUT_DIR = Path("contracts/extracted")
RECORDED = "recorded"
LEDGER = "spend.json"

SYSTEM_PROMPT = """\
You extract the fee terms of payment provider contracts into a structured contract file used by an automated \
fee audit. Return one JSON object that matches the given schema and describes one complete version of the contract.

Rules:
- Return the complete version: every fee term in force under it. For an amendment letter you also receive the \
master agreement: apply the amendment to the master agreement and return the whole amended contract, including \
the terms the letter leaves unchanged.
- version: the master agreement is version 1; Amendment No. N creates version N + 1. effective_from: the date \
from which this version applies, as an ISO 8601 date.
- contract_id: the agreement reference. party: always "provider". name: the provider's trading name as written \
in the agreement. counterparty: the first word of that name in lower case (for example "Acme Payments" gives "acme").
- Money: integer minor units (euro cents): EUR 0.04 is 4, EUR 2,500,000.00 is 250000000. Rates: integer basis \
points: 0.45% is 45.
- Volume bands: one tier per band in increasing order; up_to_minor is the band's exclusive upper limit ("less \
than"), null for the open-ended last band.
- timezone: the IANA time zone in which times and calendar months are determined. rounding.mode: half_up or \
half_even; rounding.level: transaction when each fee of each payment or payout is rounded on its own, \
invoice_line when each invoice line is rounded once. dispute_window_days: the number of days within which an \
invoice can be disputed.
- Terms: one per clause that sets a price, fee, credit, discount, minimum or cap. clause: the clause number as \
a string, for example "4.2". title: a short description of the clause. Definitions, currency, rounding, \
invoicing and dispute clauses are not terms; they give the header fields.
- Use only what the text states.

Term kinds (parameters_json: a JSON object with the parameters of the term's kind, exactly as the kind's \
parameter schema at the end defines them):
- pass_through: interchange and scheme fees charged at cost against a reference table (reference: the \
table's designation).
- markup_bps_tiered: a markup in basis points by band of monthly processed volume, where the band reached \
applies to the whole month's volume (tiering: retroactive).
- per_transaction_fixed: a fixed amount per successful payment.
- blended_rate: an all-in percentage plus a fixed amount per successful payment, by card segment (eea_consumer, \
other); failed_attempts: no_fee when declined or failed attempts are free.
- volume_discount: a lower rate on the part of a card segment's monthly volume above a threshold (tiering: \
marginal), settled as a monthly adjustment; two tiers, the rate below and the rate above the threshold.
- refund: a fee per refund, and whether the markup of the original payment is credited back.
- chargeback_fee: a fee per chargeback.
- monthly_minimum: a minimum amount of markup per month (applies_to: markup).
- payout_fee: the fee per payout on one rail (sepa, faster_payments, swift, elixir): either fixed_minor, or bps \
of the EUR equivalent with min_minor and cap_minor.
- fx_spread_cap: the maximum FX spread in basis points per payout currency against the hourly mid rate at the \
execution hour (benchmark: fx_mid_hourly, rate_time: execution_hour).
"""

# Keywords structured outputs do not accept; removed from the request schema (the full schema still validates).
_DROP = {"$schema", "$id", "title", "minimum", "maximum", "minLength", "maxLength", "maxItems", "minProperties"}


class ExtractionError(Exception):
    """The call happened but produced no usable contract (it is still recorded and paid for)."""


def _contract_schema(schema_path=SCHEMA_PATH):
    full = json.loads(Path(schema_path).read_text())
    defs = full["$defs"]

    def inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[1]])
            return {k: inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return full, defs, inline


def extraction_schema(schema_path=SCHEMA_PATH):
    """The JSON schema of one provider contract version, in the subset structured outputs accept.

    The API compiles the schema to a grammar with limits on its size and on nullable/union parameters, and a union
    of the ten term kinds exceeds them. So the header fields are constrained in full, and each term's `clause`,
    `kind` (enum) and `title`; its parameters come as a JSON string (`parameters_json`, shaped as `kind_parameters`
    describes in the prompt). `from_extraction` parses it and the full contract schema validates the result.
    `effective_to`, `component` and `approved` are left out (derived, redundant or set by the extractor).
    """
    full, defs, inline = _contract_schema(schema_path)
    kinds = defs["provider_term"]["properties"]["kind"]["enum"]
    term = _object({"clause": {"type": "string"}, "kind": {"enum": kinds}, "title": {"type": "string"},
                    "parameters_json": {"type": "string"}})
    properties = {k: _strip(inline(v)) for k, v in full["properties"].items() if k != "effective_to"}
    properties["party"] = {"const": "provider"}
    properties["terms"] = {"type": "array", "minItems": 1, "items": term}
    return {
        "type": "object",
        "required": full["required"],
        "properties": properties,
        "additionalProperties": False,
    }


def kind_parameters(schema_path=SCHEMA_PATH):
    """{kind: JSON schema of its parameters} from contract_schema.json, for the prompt."""
    _, defs, inline = _contract_schema(schema_path)
    out = {}
    for kind in defs["provider_term"]["properties"]["kind"]["enum"]:
        term = inline(defs[f"kind_{kind}"])
        params = {k: v for k, v in term["properties"].items() if k not in _TERM_KEYS}
        schema = {"type": "object", "properties": params,
                  "required": [k for k in term["required"] if k not in _TERM_KEYS]}
        if "oneOf" in term:
            schema["oneOf"] = term["oneOf"]
        out[kind] = schema
    return out


_TERM_KEYS = {"clause", "kind", "title", "component", "approved"}


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def from_extraction(term):
    """A contract term from the extraction shape: `parameters_json` parsed and merged into the term. Unparseable
    parameters stay as `parameters_json`, which the contract schema then rejects."""
    out = {k: term.get(k) for k in ("clause", "kind", "title")}
    try:
        params = json.loads(term.get("parameters_json") or "{}")
    except json.JSONDecodeError:
        params = None
    if not isinstance(params, dict):
        return {**out, "parameters_json": term.get("parameters_json")}
    return {**out, **{k: v for k, v in params.items() if k not in out}}


def _strip(node):
    if isinstance(node, list):
        return [_strip(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in _DROP and not isinstance(value, dict):
            continue
        if key == "properties":
            out[key] = {name: _strip(sub) for name, sub in value.items()}
        else:
            out[key] = _strip(value)
    if "prefixItems" in out:  # a fixed list of constants: allow those constants as items
        out["items"] = {"enum": [item["const"] for item in out.pop("prefixItems")]}
    if "propertyNames" in out:  # a map keyed by an enum: one optional property per key
        value_schema = out.pop("additionalProperties")
        out["properties"] = {name: value_schema for name in out.pop("propertyNames")["enum"]}
        out["additionalProperties"] = False
    if out.get("minItems", 0) > 1:
        out["minItems"] = 1
    return out


def source_files(name, text_dir=TEXT_DIR):
    """[(role, path)] for a contract version: the master alone, or the master, earlier letters and this letter."""
    match = re.fullmatch(r"(?P<base>.+)-v(?P<version>\d+)", name)
    if not match:
        raise ExtractionError(f"{name}: expected a name like northgate-v2")
    base, version = match["base"], int(match["version"])
    files = [("master_agreement", Path(text_dir) / f"{base}-v1.md")]
    files += [("earlier_amendment_letter", Path(text_dir) / f"{base}-v{v}.md") for v in range(2, version)]
    if version > 1:
        files.append(("amendment_letter", Path(text_dir) / f"{name}.md"))
    missing = [str(path) for _, path in files if not path.exists()]
    if missing:
        raise ExtractionError(f"{name}: missing contract text {', '.join(missing)}")
    return files


def build_request(name, model, config, text_dir=TEXT_DIR):
    """Messages API arguments for one contract version (deterministic for given texts and config)."""
    files = source_files(name, text_dir)
    documents = "\n\n".join(f"<document role=\"{role}\">\n{path.read_text()}</document>" for role, path in files)
    if len(files) == 1:
        task = "Extract the contract version that this agreement sets out."
    else:
        task = "Extract the complete contract version that the amendment letter creates."
    return {
        "model": model,
        "max_tokens": config.max_tokens,
        "system": f"{SYSTEM_PROMPT}\nParameter schema per kind:\n"
                  f"{json.dumps(kind_parameters(), indent=1, sort_keys=True)}\n",
        "messages": [{"role": "user", "content": f"{documents}\n\n{task}"}],
        "output_config": {"effort": config.effort, "format": {"type": "json_schema", "schema": extraction_schema()}},
    }


def prompt_sha256(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _usage(response):
    u = response.usage
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
    }


def _contract_yaml(doc, model, files, timestamp):
    sources = ", ".join(_rel(path) for _, path in files)
    header = [
        f"# Extracted by {model} from {sources} on {timestamp}.",
        "# NOT APPROVED: every term has approved: false, so feeaudit.contracts refuses this file. Review each term",
        "# against the text, set approved: true, then promote the file (docs/llm-extraction.md).",
    ]
    out = dict(doc)
    if isinstance(out.get("effective_from"), str):
        try:
            out["effective_from"] = dt.date.fromisoformat(out["effective_from"])
        except ValueError:
            pass
    return "\n".join(header) + "\n" + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=120)


def _mark_unapproved(term):
    """The term with `approved: false` after its title (or at the end)."""
    out = {}
    for key, value in term.items():
        if key != "approved":
            out[key] = value
        if key == "title":
            out["approved"] = False
    out.setdefault("approved", False)
    return out


def extract(name, client, config, text_dir=TEXT_DIR, out_dir=OUT_DIR, now=None):
    """Extract contract version `name` (e.g. 'northgate-v2'); return a summary dict.

    Raises BudgetError before any paid call when prices are unverified or the call could exceed the budget, and
    ExtractionError when the response is unusable (after recording it).
    """
    model = config.model()
    prices = config.prices_for(model)
    files = source_files(name, text_dir)
    request = build_request(name, model, config, text_dir)
    recorded_dir = Path(out_dir) / RECORDED
    ledger_path = recorded_dir / LEDGER
    ledger = load_ledger(ledger_path)

    counted = client.messages.count_tokens(**{k: v for k, v in request.items() if k != "max_tokens"}).input_tokens
    estimate = call_cost(prices, counted, config.max_tokens)
    check_budget(config, ledger, estimate)

    response = client.messages.create(**request)
    timestamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    usage = _usage(response)
    cost = call_cost(prices, usage["input_tokens"], usage["output_tokens"],
                     usage["cache_creation_input_tokens"], usage["cache_read_input_tokens"])
    digest = prompt_sha256(request)
    ledger["calls"].append({"name": name, "model": model, "timestamp": timestamp, "prompt_sha256": digest, **usage,
                            "cost_usd": usd(cost)})
    save_ledger(ledger_path, ledger)

    record = {
        "name": name,
        "model": model,
        "timestamp": timestamp,
        "prompt_sha256": digest,
        "sources": {_rel(path): hashlib.sha256(path.read_bytes()).hexdigest() for _, path in files},
        "usage": usage,
        "prices_usd_per_million_tokens": {k: usd(v) for k, v in prices.items()},
        "cost_usd": usd(cost),
        "estimate": {"input_tokens": counted, "max_output_tokens": config.max_tokens, "cost_usd": usd(estimate)},
        "request": request,
        "response": response.model_dump(mode="json"),
    }
    error, doc = None, None
    text = "".join(block.text for block in response.content if block.type == "text")
    if response.stop_reason != "end_turn":
        error = f"stop_reason {response.stop_reason!r}, expected 'end_turn'"
    else:
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            error = f"response is not JSON: {exc}"
        if doc is not None and not (isinstance(doc, dict) and isinstance(doc.get("terms"), list)):
            doc, error = None, "response JSON has no terms list"
    problems = []
    if doc is not None:
        doc["terms"] = [_mark_unapproved(from_extraction(t)) if isinstance(t, dict) else t for t in doc["terms"]]
        problems = [f"{p}: {m}" for p, m in validate_contract(doc)]
    record["validation_errors"] = problems
    record["error"] = error
    recorded_dir.mkdir(parents=True, exist_ok=True)
    (recorded_dir / f"{name}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if error:
        raise ExtractionError(f"{name}: {error} (recorded in {recorded_dir / f'{name}.json'})")
    out_path = Path(out_dir) / f"{name}.yml"
    out_path.write_text(_contract_yaml(doc, model, files, timestamp))
    return {"name": name, "path": out_path, "cost_usd": cost, "usage": usage, "validation_errors": problems,
            "total_usd": ledger["total_usd"]}
