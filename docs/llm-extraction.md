# LLM contract extraction

An optional step that reads the provider contracts as prose and turns them back into contract YAML with a Claude model (Anthropic API), then scores the result field by field against the hand-written YAML. It is not part of `make all`: the extraction is paid and not deterministic, so only its recorded outputs are committed and CI only scores them.

## What runs

| Step | Command | Network | Writes |
|---|---|---|---|
| Contract prose | `python -m generator.contract_text` | no | `contracts/text/*.md` |
| Extraction | `python -m feeaudit.extraction extract [--only NAME]` | yes, paid | `contracts/extracted/<name>.yml`, `contracts/extracted/recorded/<name>.json`, `contracts/extracted/recorded/spend.json` |
| Scoring | `make extraction-score` (`python -m feeaudit.extraction score`) | no | `evaluation.extraction_scores` in `warehouse/fees.duckdb` |

- **Prose.** Deterministic templates render every file in `contracts/providers/` as legal text: version 1 as a master agreement with numbered clauses that match the YAML clause ids, defined terms, cross-references and amounts in figures and words; every later version as an amendment letter that replaces or inserts only the clauses whose wording changed (Northgate: clause 4.2, the EUR 2.5M–8M markup band; Kestrel: new clause 2.4, the Elixir rail). The files are committed; a test checks they equal a fresh render.
- **Extraction.** One Messages API call per contract version (`NAME` is the file stem, e.g. `northgate-v2`). For an amendment letter the request also carries the master agreement, and the model returns the complete amended version. The response is constrained by structured outputs (`output_config.format`) with a JSON schema derived from `feeaudit/contract_schema.json` (`extraction_schema()` in `feeaudit/extraction/extract.py`), then validated against the full schema; any errors are printed and recorded. The model is `claude-opus-5-5` unless env `FEEAUDIT_LLM_MODEL` names another; the SDK is in `requirements-llm.txt`, outside the default install.
- **Recording.** `recorded/<name>.json` holds the full request (system prompt, documents, schema), the full response, the model, the SHA-256 of the request, the SHA-256 of each source text, the token usage, the prices used, the cost, the pre-call estimate and a timestamp.
- **Scoring.** For each ground-truth version: every header field and every term parameter, terms matched by clause id. Row columns: `contract`, `version`, `field_path` (e.g. `terms[4.2].tiers[1].bps`), `expected`, `extracted` (JSON values; `NULL` when absent), `correct`. Titles, the redundant `component` and `approved` are not scored; missing fields and invented fields or clauses count as wrong. Versions without an extracted file are listed as not run, and the command still exits 0. The command prints the accuracy per version, per contract and overall.

## The approval gate

Every extracted term is written with `approved: false`. `feeaudit.contracts` (and so `make contracts` and the engine) refuses to load any term with `approved: false`, naming the file and the clause, and it never reads `contracts/extracted/`. Nothing approves a term automatically: a person compares each term with the contract text, corrects it if needed and sets `approved: true`.

To promote a reviewed file:

1. Review every term of `contracts/extracted/<name>.yml` against `contracts/text/<name>.md` (and the master agreement for an amendment); fix what is wrong and set `approved: true` on each term.
2. Copy it to `contracts/providers/<name>.yml` (replacing the file there) and run `make contracts` to validate it with the other versions of the contract.
3. Run `make all`. In this project `contracts/providers/` is also the ground truth the generator bills from, so a promoted file that differs from it changes the synthetic world; `make extraction-score` at 100% means the promotion changes nothing.

## The budget

`config/llm.yml` holds the budget (USD 5.00 in total), `max_tokens`, the effort level and the prices per million input, output, cache-write and cache-read tokens for each model.

- **Cost of a call** = (input tokens × input price + output tokens × output price + cache-write tokens × cache-write price + cache-read tokens × cache-read price) / 1,000,000, from the usage the API returns, in exact decimals. Output tokens include the model's thinking.
- **Ledger.** `recorded/spend.json` lists every call with its cost and keeps the total. It is updated straight after each response, before the response is parsed, so a failed or refused-by-the-model response is still counted.
- **Guard.** Before each call the extractor counts the request's input tokens (the free token-counting endpoint) and takes the worst case of the call: those input tokens plus `max_tokens` of output. If the ledger total plus that worst case would exceed the budget, it does not call the API. It also refuses while `prices_verified` is `false` or when the model has no prices in the file.

## Before the first real run

1. Check the prices in `config/llm.yml` against Anthropic's pricing page for the model you will use, correct them if needed, and set `prices_verified: true`.
2. `pip install -r requirements-llm.txt` and export `ANTHROPIC_API_KEY`.
3. Run `python -m feeaudit.extraction extract --only northgate-v1` first and read the recorded cost, then run the rest.
4. Commit `contracts/extracted/` (the YAML files, `recorded/*.json` and `spend.json`), then `make extraction-score`.
