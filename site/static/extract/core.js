// The extraction page's request and post-processing, without the DOM or Puter, so tests/js/ runs the same code.
//
// `data` is extraction.json, written by `python -m feeaudit.extraction export`. It holds the prompt, the schemas and the
// model settings; nothing of the prompt is written here. The functions below port feeaudit/extraction/extract.py:
// prompt() (the user message), the response checks of extract(), from_extraction(), _mark_unapproved() and
// _contract_yaml(). One difference follows from the languages: JavaScript orders integer-like object keys ("0", "12")
// before other keys, where Python keeps the order of the answer; no contract field has such a key.

import { dump, visit } from "./vendor/js-yaml.esm.min.mjs";

// Anthropic itself, as Puter names it (docs.puter.com/AI/chat, Providers); with `fallback: false` Puter never
// sends the request to another provider.
export const PROVIDER = "claude";

const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

/** The user message for [{role, text}] (master agreement, then amendment letter), as prompt() builds it. */
export function buildMessages(data, documents) {
  const body = documents.map((d) => `<document role="${d.role}">\n${d.text}</document>`).join("\n\n");
  const task = documents.length === 1 ? data.tasks.master_agreement : data.tasks.amendment_letter;
  return [{ role: "user", content: `${body}\n\n${task}` }];
}

/** A pasted document as a text file reads: line feeds only, ending with one. */
export function asFileText(text) {
  const lf = text.replace(/\r\n?/g, "\n");
  return lf.endsWith("\n") ? lf : `${lf}\n`;
}

/**
 * Arguments of puter.ai.chat(messages, testMode, options). The system prompt goes as the first message (Puter's
 * messages have a system role). Effort is not sent: Puter documents no effort option for Anthropic models, so the
 * model's default effort applies. `thinking: null` sends no thinking configuration, as the Python request does.
 */
export function chatRequest(data, documents) {
  return {
    messages: [{ role: "system", content: data.system }, ...buildMessages(data, documents)],
    options: {
      model: data.model,
      provider: PROVIDER,
      fallback: false,
      max_tokens: data.max_tokens,
      outputFormat: { type: "json_schema", schema: data.extraction_schema },
      normalize: true,
      thinking: null,
    },
  };
}

/** The answer's text: a string on a normalized response, else the text blocks of Anthropic's content array. */
export function responseText(response) {
  const content = response?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.filter((b) => b?.type === "text").map((b) => b.text).join("");
  return "";
}

/**
 * Why the answer is unusable, or null. extract() accepts only stop_reason "end_turn"; on a normalized response that is
 * finish_reason "stop" (which also stands for a stop sequence; none is sent), and Puter also reports the native value.
 */
export function stopProblem(response) {
  const finish = response?.finish_reason;
  const native = response?.stopReason;
  if (finish === "length" || native === "max_tokens") {
    return `the answer was cut off at max_tokens (finish_reason "length")`;
  }
  if (finish !== "stop" || (native !== undefined && native !== "end_turn")) {
    return `finish_reason ${JSON.stringify(finish)}, stopReason ${JSON.stringify(native)}; expected "stop" and "end_turn"`;
  }
  return null;
}

/** from_extraction(): `parameters_json` parsed and merged into the term; unparseable, it stays for the schema to reject. */
export function fromExtraction(term) {
  const out = {};
  for (const key of ["clause", "kind", "title"]) out[key] = own(term, key) ? term[key] : null;
  // Python: json.loads(term.get("parameters_json") or "{}"). The structured output makes it a string.
  let params;
  try {
    params = JSON.parse(term.parameters_json || "{}");
  } catch {
    params = null;
  }
  if (!isObject(params)) return { ...out, parameters_json: own(term, "parameters_json") ? term.parameters_json : null };
  const merged = { ...out };
  for (const [key, value] of Object.entries(params)) if (!own(out, key)) merged[key] = value;
  return merged;
}

/** _mark_unapproved(): the term with `approved: false` after its title (or at the end). */
export function markUnapproved(term) {
  const out = {};
  for (const [key, value] of Object.entries(term)) {
    if (key !== "approved") out[key] = value;
    if (key === "title") out.approved = false;
  }
  if (!own(out, "approved")) out.approved = false;
  return out;
}

/** A YYYY-MM-DD calendar date: Python's date check for format "date" (jsonschema) and for effective_from. */
export function isIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [year, month, day] = match.slice(1).map(Number);
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  return year >= 1 && days !== undefined && day >= 1 && day <= days;
}

function jsonPath(instancePath) {
  let path = "$";
  for (const raw of instancePath.split("/").slice(1)) {
    const key = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    path += /^\d+$/.test(key) ? `[${key}]` : /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ? `.${key}` : `[${JSON.stringify(key)}]`;
  }
  return path;
}

function problem(error) {
  const p = error.params ?? {};
  let detail = "";
  if (p.additionalProperty !== undefined) detail = `: ${p.additionalProperty}`;
  else if (p.allowedValues !== undefined) detail = `: ${p.allowedValues.map((v) => JSON.stringify(v)).join(", ")}`;
  else if (p.allowedValue !== undefined) detail = `: ${JSON.stringify(p.allowedValue)}`;
  return { path: jsonPath(error.instancePath), message: `${error.message}${detail}`, at: error.instancePath.split("/").slice(1) };
}

// validate_contract() sorts by (path parts as strings, message).
function byPathThenMessage(a, b) {
  for (let i = 0; i < Math.min(a.at.length, b.at.length); i += 1) {
    if (a.at[i] !== b.at[i]) return a.at[i] < b.at[i] ? -1 : 1;
  }
  if (a.at.length !== b.at.length) return a.at.length - b.at.length;
  return a.message < b.message ? -1 : a.message > b.message ? 1 : 0;
}

/**
 * A validator of the full contract schema (JSON Schema 2020-12) with Ajv: doc -> [{path, message}], ordered as
 * validate_contract() orders them. strictTypes and strictTuples are off because the schema relies on the standard,
 * lenient meaning of `items` and `prefixItems`, as Python's jsonschema does; unknown keywords still fail to compile.
 * Ajv's extra 'must match "then" schema' errors are dropped: the errors inside `then` are reported themselves.
 */
export function contractValidator(Ajv2020, schema) {
  const ajv = new Ajv2020({ allErrors: true, strictTypes: false, strictTuples: false });
  ajv.addFormat("date", { type: "string", validate: isIsoDate });
  const validate = ajv.compile(schema);
  return (doc) => {
    if (validate(doc)) return [];
    return validate.errors
      .filter((e) => e.keyword !== "if")
      .map(problem)
      .sort(byPathThenMessage)
      .map(({ path, message }) => ({ path, message }));
  };
}

/**
 * The response checks of extract() on the answer's text: {error} when there is no contract, else {doc, problems}
 * with every term passed through fromExtraction() and markUnapproved() and checked against the contract schema.
 */
export function postProcess(text, validate) {
  let doc;
  try {
    doc = JSON.parse(text);
  } catch (exc) {
    return { error: `response is not JSON: ${exc.message}` };
  }
  if (!isObject(doc) || !Array.isArray(doc.terms)) return { error: "response JSON has no terms list" };
  doc = { ...doc, terms: doc.terms.map((t) => (isObject(t) ? markUnapproved(fromExtraction(t)) : t)) };
  return { doc, problems: validate(doc) };
}

/** UTC time as extract() writes it: 2026-10-14T16:58:05Z. */
export function timestamp(now = new Date()) {
  return now.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * _contract_yaml(): the provenance line, the NOT APPROVED notice and the document. Block style as PyYAML's
 * safe_dump(sort_keys=False, allow_unicode=True, width=120) writes it, with effective_from as a plain date.
 */
export function contractYaml(doc, { model, sources, timestamp: when, notice }) {
  const header = [`# Extracted by ${model} through Puter from ${sources.join(", ")} on ${when}.`, ...notice];
  const out = { ...doc };
  if (typeof out.effective_from === "string" && isIsoDate(out.effective_from)) {
    out.effective_from = new Date(`${out.effective_from}T00:00:00Z`);
  }
  const body = dump(out, {
    seqNoIndent: true,
    lineWidth: 120,
    transform: (documents) =>
      visit(documents, (node) => {
        if (node.kind === "scalar" && node.tag === "tag:yaml.org,2002:timestamp") node.value = node.value.slice(0, 10);
      }),
  });
  return `${header.join("\n")}\n${body}`;
}
