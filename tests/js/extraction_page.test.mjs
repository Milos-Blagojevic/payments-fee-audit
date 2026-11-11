// The site's extraction page (site/static/extract/core.js) against the Python extraction: the recorded responses give
// the committed contracts/extracted/*.yml, the page sends the messages build_request() sends, and the contract schema
// check agrees with Python's. Offline; run with `node --test tests/js/*.test.mjs` (CI does).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildMessages, chatRequest, contractValidator, contractYaml, postProcess, responseText, stopProblem,
} from "../../site/static/extract/core.js";
import { CORE_SCHEMA, load } from "../../site/static/extract/vendor/js-yaml.esm.min.mjs";
// Loaded as a module, the UMD bundle sets globalThis.ajv2020, as it sets window.ajv2020 on the page.
import "../../site/static/extract/vendor/ajv2020.min.js";

const repo = new URL("../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, repo), "utf8");
const data = JSON.parse(read("site/static/extract/extraction.json"));
const validate = contractValidator(globalThis.ajv2020, data.contract_schema);
const withoutHeader = (yaml) => yaml.split("\n").filter((line) => !line.startsWith("#")).join("\n");

for (const sample of data.samples) {
  test(`${sample.name}: the recorded response gives the committed extraction`, () => {
    const record = JSON.parse(read(`contracts/extracted/recorded/${sample.name}.json`));
    // A native Anthropic answer as Puter returns it without normalization: the content blocks, finish_reason "stop"
    // and the real stop reason in stopReason (docs.puter.com/Objects/chatresponse).
    const response = { message: { role: "assistant", content: record.response.content }, finish_reason: "stop",
      stopReason: record.response.stop_reason };
    assert.equal(stopProblem(response), null);
    const result = postProcess(responseText(response), validate);
    assert.equal(result.error, undefined);
    assert.deepEqual(result.problems, record.validation_errors);
    assert.ok(result.doc.terms.every((term) => term.approved === false));
    const yaml = contractYaml(result.doc, { model: record.model, sources: sample.documents.map((d) => d.path),
      timestamp: record.timestamp, notice: data.yaml_notice });
    assert.equal(withoutHeader(yaml), withoutHeader(read(`contracts/extracted/${sample.name}.yml`)));
    assert.deepEqual(yaml.split("\n").slice(1, 3), data.yaml_notice);
  });

  test(`${sample.name}: the page sends the messages build_request() sends`, () => {
    const documents = sample.documents.map(({ role, text }) => ({ role, text }));
    assert.deepEqual(buildMessages(data, documents), sample.messages);
    const { messages, options } = chatRequest(data, documents);
    assert.deepEqual(messages, [{ role: "system", content: data.system }, ...sample.messages]);
    assert.deepEqual(options.outputFormat, { type: "json_schema", schema: data.extraction_schema });
    assert.equal(options.max_tokens, data.max_tokens);
  });

  test(`${sample.name}: the hand-written contract passes the schema check`, () => {
    assert.deepEqual(validate(load(sample.hand_written.yaml, { schema: CORE_SCHEMA })), []);
  });
}

test("unparseable parameters_json is kept and rejected by the contract schema, with its path", () => {
  const answer = JSON.parse(responseText({ message: { content: JSON.parse(read(
    "contracts/extracted/recorded/northgate-v1.json")).response.content } }));
  answer.terms[1].parameters_json = "{oops";
  const { doc, problems } = postProcess(JSON.stringify(answer), validate);
  assert.equal(doc.terms[1].parameters_json, "{oops");
  assert.equal(doc.terms[1].approved, false);
  assert.ok(problems.some((p) => p.path === "$.terms[1]" && p.message.includes("parameters_json")), JSON.stringify(problems));
});

test("an answer cut off at max_tokens is reported and not post-processed", () => {
  assert.match(stopProblem({ finish_reason: "length", stopReason: "max_tokens" }), /cut off at max_tokens/);
  assert.match(stopProblem({ finish_reason: "content_filter", stopReason: "refusal" }), /expected "stop"/);
  assert.equal(stopProblem({ finish_reason: "stop", stopReason: "end_turn" }), null);
});

test("a date that is not on the calendar fails format date, as in Python", () => {
  const doc = load(data.samples[0].hand_written.yaml, { schema: CORE_SCHEMA });
  doc.effective_from = "2026-02-30";
  assert.deepEqual(validate(doc).map((p) => p.path), ["$.effective_from"]);
});
