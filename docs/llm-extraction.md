# LLM contract extraction

An optional step that reads the provider contracts as prose and turns them back into contract YAML with a Claude model (Anthropic API), then scores the result field by field against the hand-written YAML. It is not part of `make all`: the extraction is paid and not deterministic, so only its recorded outputs are committed and CI only scores them.

## What runs

| Step | Command | Network | Writes |
|---|---|---|---|
| Contract prose | `python -m generator.contract_text` | no | `contracts/text/*.md` |
| Extraction | `python -m feeaudit.extraction extract [--only NAME]` | yes, paid | `contracts/extracted/<name>.yml`, `contracts/extracted/recorded/<name>.json`, `contracts/extracted/recorded/spend.json` |
| Scoring | `make extraction-score` (`python -m feeaudit.extraction score`) | no | `evaluation.extraction_scores` in `warehouse/fees.duckdb` |
| Page data | `make extraction-export` (`python -m feeaudit.extraction export`) | no | `site/static/extract/extraction.json` |

- **Prose.** Deterministic templates render every file in `contracts/providers/` as legal text: version 1 as a master agreement with numbered clauses that match the YAML clause ids, defined terms, cross-references and amounts in figures and words; every later version as an amendment letter that replaces or inserts only the clauses whose wording changed (Northgate: clause 4.2, the EUR 2.5M–8M markup band; Kestrel: new clause 2.4, the Elixir rail). The files are committed; a test checks they equal a fresh render.
- **Extraction.** One Messages API call per contract version (`NAME` is the file stem, e.g. `northgate-v2`). For an amendment letter the request also carries the master agreement, and the model returns the complete amended version. The response is constrained by structured outputs (`output_config.format`) with a JSON schema derived from `feeaudit/contract_schema.json` (`extraction_schema()` in `feeaudit/extraction/extract.py`): the header fields in full, and each term's `clause`, `kind` and `title`. The API compiles the schema to a grammar with size and union limits that a union of all ten term kinds exceeds, so each term's parameters come as a JSON string (`parameters_json`), shaped by the per-kind parameter schemas the system prompt lists. The result is validated against the full contract schema; any errors are printed and recorded. The model is `claude-opus-5-5` unless env `FEEAUDIT_LLM_MODEL` names another; the SDK is in `requirements-llm.txt`, outside the default install.
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

## In the browser

The report site has a page, `/extract/` (`site/static/extract/`, linked from the Overview), that runs one extraction in a visitor's browser with [Puter.js](https://docs.puter.com). The visitor picks one of the five sample versions or pastes a master agreement and, optionally, an amendment letter as plain text, and gets a draft contract YAML. The page never writes to the repository, and the approval gate, the budget code and `make all` are not involved.

| Part | Runs | Code |
|---|---|---|
| Prompt, schemas, model settings, the five samples with their hand-written YAML and recorded cost | `make extraction-export` (offline, free) writes `site/static/extract/extraction.json`; it is committed, CI checks it equals a fresh export, and `make site` copies `site/static/` into the build unchanged | `feeaudit/extraction/export.py`, using `prompt()` like `build_request()` |
| Sign-in, model check, the call | the visitor's browser, then Puter, then Anthropic | `site/static/extract/page.js` |
| Response checks, `from_extraction`, `_mark_unapproved`, the YAML | the visitor's browser | `site/static/extract/core.js` |
| Schema check against the full `feeaudit/contract_schema.json` (JSON Schema 2020-12) | the visitor's browser | Ajv, `site/static/extract/vendor/` |

- **Who pays.** The visitor does, under Puter's [user-pays model](https://docs.puter.com/user-pays-model/): they sign in with their own Puter account and the call is charged to it. The site holds no API key, the owner pays nothing, and the browser keeps no budget or ledger. Before the first call the page says plainly that the text goes to Puter and to Anthropic, that the visitor's Puter account pays, that the recorded sample runs cost USD 0.040–0.049 each at Anthropic's list prices and that Puter's charge may differ, and that the samples are synthetic and confidential contracts should not be pasted. The visitor has to tick that they have read it. After the call the page shows Puter's token counts (`usageDetails`) and its charge (`usage.cost`). Sign-in opens a popup, so `puter.auth.signIn()` is called from the click itself, before anything is awaited.
- **Provider pin.** The request carries `provider: "claude"` (Anthropic itself, in Puter's [Providers](https://docs.puter.com/AI/chat/#providers) section) and `fallback: false`, so Puter answers from Anthropic or fails and never retries the contract text on another provider. Before the call the page checks that `puter.ai.listModelProviders()` includes `claude` and that `puter.ai.listModels("claude")` lists the model, under its id or an alias. If either check fails, it stops without sending anything and never substitutes another model.
- **The same prompt.** The page builds the messages from the export's documents and task sentences. `tests/js/` checks that, for every sample, they equal the messages the export records, and `tests/test_extraction_export.py` checks that those equal what `build_request()` sends. Pasted text is first normalised the way a file reads: line feeds only, ending with a newline.
- **What differs from the Python run:**
  - The system prompt is the first message, with role `system`, because Puter's `puter.ai.chat` takes no separate system parameter.
  - Structured output is `outputFormat: {type: "json_schema", schema}` with the same `extraction_schema()`. The call also sets `normalize: true`, so the answer comes as a string, `finish_reason` uses OpenAI's values and Anthropic's own stop reason is in `stopReason`. The page accepts only `finish_reason` `"stop"` with `stopReason` `"end_turn"`. On `"length"` (cut off at `max_tokens`), or anything else, it reports the answer and builds no contract.
  - Effort is not sent. Puter documents `reasoning_effort` for OpenAI, Moonshot, Meta and some Gemini models, and no effort option for Anthropic models, so the model's default effort applies. For Claude Opus 5.5 that default is `medium` ([Anthropic, Effort](https://platform.claude.com/docs/en/build-with-claude/effort)); the Python run sends `high`. For thinking the page passes `thinking: null`, which in Puter's terms sends no thinking configuration. That matches the Python request, which sends none either.
  - There is no token count, no worst-case guard and no ledger. While the call runs, Puter holds the most it could cost against the visitor's balance ([Rate limits and quotas](https://docs.puter.com/rate-limits-and-quotas/)).
  - Schema errors come from Ajv rather than Python's jsonschema: the same paths, in different words. The loader's further checks (time zone, duplicate clauses, order of volume bands) do not run in the browser. They run when the file is loaded with `feeaudit.contracts`.
  - The first header line reads `# Extracted by <model> through Puter from <sources> on <timestamp>.`. The sources are the files of the sample, or "pasted master agreement" and "pasted amendment letter".
  - Nothing is recorded: no request or response file and no ledger entry. The page stores nothing in Puter's key-value store or file storage, and the download is the only copy of the result. Puter.js keeps its own sign-in session in the browser.
- **Still unapproved.** Every term is written with `approved: false` after its title, under the same NOT APPROVED header lines as `contracts/extracted/`. The page shows the draft next to the hand-written YAML of a sample. To use a draft, follow the approval gate above.
- **Parity.** `node --test tests/js/*.test.mjs` (in CI) feeds each of the five recorded responses through the page's post-processing and checks that the YAML equals `contracts/extracted/<name>.yml` below the header comment. It also checks the schema validator on the hand-written files and on broken input.
- **Libraries.** Puter.js loads from `https://js.puter.com/v2/`, Puter's hosted SDK, which has no pinned version. Ajv (ajv-dist 8.17.1, the JSON Schema 2020-12 build) and js-yaml 5.5.0 are vendored, unmodified, in `site/static/extract/vendor/` with their licences and SHA-256 checksums.
