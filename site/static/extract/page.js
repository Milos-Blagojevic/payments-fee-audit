// The extraction page: reads extraction.json, signs the visitor in to Puter, checks that Puter serves the model from
// Anthropic, calls puter.ai.chat and shows the draft contract. Request and post-processing are in core.js.
// Stores nothing: no Puter key-value store, no Puter files, no browser storage of its own.

import "./vendor/ajv2020.min.js"; // sets window.ajv2020
import {
  PROVIDER, asFileText, chatRequest, contractValidator, contractYaml, postProcess, responseText, stopProblem, timestamp,
} from "./core.js";

const $ = (id) => document.getElementById(id);
const state = { data: null, validate: null, running: false };
const fmt = new Intl.NumberFormat("en");

function log(text, kind = "step") {
  const item = document.createElement("li");
  item.className = kind;
  item.textContent = text;
  $("log").append(item);
  return item;
}

function describe(error) {
  if (typeof error === "string") return error;
  if (error instanceof Error && !error.code) return error.message;
  const inner = error?.error !== null && typeof error?.error === "object" ? error.error : error;
  const code = inner?.code ?? (typeof error?.error === "string" ? error.error : undefined);
  const message = inner?.message ?? inner?.msg ?? error?.msg;
  const text = [code, message].filter(Boolean).join(": ");
  return text || JSON.stringify(error);
}

function source() {
  return document.querySelector("input[name=source]:checked").value;
}

function sample() {
  return state.data.samples.find((s) => s.name === $("sample").value);
}

// What will be sent: {name, documents, sources, handWritten} or {error}.
function currentInput() {
  if (source() === "sample") {
    const s = sample();
    return { name: s.name, documents: s.documents.map(({ role, text }) => ({ role, text })),
      sources: s.documents.map((d) => d.path), handWritten: s.hand_written };
  }
  const master = $("master").value;
  const letter = $("letter").value;
  if (!master.trim()) return { error: "Paste the master agreement first." };
  const documents = [{ role: "master_agreement", text: asFileText(master) }];
  const sources = ["pasted master agreement"];
  if (letter.trim()) {
    documents.push({ role: "amendment_letter", text: asFileText(letter) });
    sources.push("pasted amendment letter");
  }
  return { name: "extracted", documents, sources, handWritten: null };
}

function showSample() {
  const s = sample();
  const r = s.recorded;
  $("sample-recorded").textContent = r
    ? `Recorded run on ${r.timestamp.slice(0, 10)}: ${fmt.format(r.input_tokens)} input and ` +
      `${fmt.format(r.output_tokens)} output tokens, USD ${Number(r.cost_usd).toFixed(4)} at Anthropic's list prices.`
    : "";
  const box = $("sample-documents");
  box.replaceChildren();
  for (const d of s.documents) {
    const title = document.createElement("p");
    title.innerHTML = `<code></code> as <code></code>`;
    title.children[0].textContent = d.path;
    title.children[1].textContent = d.role;
    const text = document.createElement("pre");
    text.textContent = d.text;
    box.append(title, text);
  }
}

function syncControls() {
  const paste = source() === "paste";
  document.querySelector(".when-sample").hidden = paste;
  document.querySelector(".when-paste").hidden = !paste;
  $("sample").disabled = paste;
  $("master").disabled = !paste;
  $("letter").disabled = !paste;
  $("extract").disabled = state.running || !state.data || !$("ack").checked;
}

function costRange(samples) {
  const costs = samples.map((s) => s.recorded && Number(s.recorded.cost_usd)).filter((c) => c);
  if (!costs.length) return "(no recorded run)";
  return `${Math.min(...costs).toFixed(3)}–${Math.max(...costs).toFixed(3)}`;
}

async function init() {
  const response = await fetch(new URL("extraction.json", import.meta.url));
  if (!response.ok) throw new Error(`extraction.json: HTTP ${response.status}`);
  const data = await response.json();
  state.validate = contractValidator(globalThis.ajv2020, data.contract_schema);
  state.data = data;
  for (const el of document.querySelectorAll(".model")) el.textContent = data.model;
  for (const el of document.querySelectorAll(".max-tokens")) el.textContent = fmt.format(data.max_tokens);
  $("effort").textContent = data.effort;
  $("cost-range").textContent = costRange(data.samples);
  for (const s of data.samples) $("sample").append(new Option(s.name, s.name));
  showSample();
  syncControls();
  if (typeof puter === "undefined") log("Puter.js did not load from js.puter.com, so nothing can be sent.", "error");
}

function showUsage(response) {
  const u = response.usageDetails;
  if (!u) {
    log("Puter returned no usage details.", "info");
    return;
  }
  const cache = (u.cacheReadTokens ?? 0) + (u.cacheWrite5mTokens ?? 0) + (u.cacheWrite1hTokens ?? 0);
  let text = `Usage: ${fmt.format(u.inputTokens ?? 0)} input` + (cache ? ` (+ ${fmt.format(cache)} cache)` : "") +
    ` and ${fmt.format(u.outputTokens ?? 0)} output tokens`;
  if (u.reasoningTokens) text += `, ${fmt.format(u.reasoningTokens)} of them thinking`;
  const cost = response.usage?.cost; // microcents: USD 0.01 = 1,000,000
  if (typeof cost === "number") text += `. Puter charged USD ${(cost / 1e8).toFixed(4)}`;
  log(`${text}.`, "info");
}

function showRaw(text) {
  if (!text) return;
  const item = log("The model's answer, as received:", "info");
  const pre = document.createElement("pre");
  pre.textContent = text;
  item.append(pre);
}

function showResult(input, yaml, problems) {
  const box = $("problems");
  box.replaceChildren();
  const summary = document.createElement("p");
  if (problems.length) {
    summary.className = "error";
    summary.textContent = `The contract schema check (feeaudit/contract_schema.json) found ${problems.length} ` +
      `problem${problems.length === 1 ? "" : "s"}:`;
    const list = document.createElement("ul");
    for (const p of problems) {
      const item = document.createElement("li");
      const path = document.createElement("code");
      path.textContent = p.path;
      item.append(path, ` ${p.message}`);
      list.append(item);
    }
    box.append(summary, list);
  } else {
    summary.textContent = "The draft passes the contract schema check (feeaudit/contract_schema.json).";
    box.append(summary);
  }
  $("yaml").textContent = yaml;
  $("download").onclick = () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([yaml], { type: "application/yaml" }));
    link.download = `${input.name}.yml`;
    link.click();
    URL.revokeObjectURL(link.href);
  };
  $("hand-written-column").hidden = !input.handWritten;
  if (input.handWritten) {
    $("hand-written-path").textContent = input.handWritten.path;
    $("hand-written").textContent = input.handWritten.yaml;
  }
  $("result").hidden = false;
}

async function run(input, signedIn) {
  const { data } = state;
  try {
    await signedIn;
    const user = await puter.auth.getUser();
    log(`Signed in to Puter as ${user?.username ?? "(unknown)"}; this account pays for the call.`, "done");

    log(`Checking that Puter serves ${data.model} from provider "${PROVIDER}" (Anthropic)…`);
    const providers = await puter.ai.listModelProviders();
    if (!providers.includes(PROVIDER)) {
      log(`Puter does not list the provider "${PROVIDER}". Nothing was sent; the page never uses another provider.`, "error");
      return;
    }
    const models = await puter.ai.listModels(PROVIDER);
    const served = models.find((m) => m.id === data.model || (m.aliases ?? []).includes(data.model));
    if (!served) {
      log(`Puter does not serve ${data.model} from provider "${PROVIDER}". Nothing was sent; the page never ` +
        "switches to another model.", "error");
      return;
    }
    const price = served.cost?.currency === "usd-cents" && served.cost.tokens
      ? ` at USD ${(served.cost.input * 1e4 / served.cost.tokens).toFixed(2)} input and ` +
        `${(served.cost.output * 1e4 / served.cost.tokens).toFixed(2)} output per million tokens`
      : "";
    log(`Puter serves ${served.id} from ${served.provider}${price}.`, "done");

    const { messages, options } = chatRequest(data, input.documents);
    log(`Sending ${input.sources.join(" and ")} to ${data.model}; this takes a minute or so…`);
    const response = await puter.ai.chat(messages, false, options);
    showUsage(response);
    const text = responseText(response);
    const stopped = stopProblem(response);
    if (stopped) {
      log(`No contract: ${stopped}.`, "error");
      showRaw(text);
      return;
    }
    const result = postProcess(text, state.validate);
    if (result.error) {
      log(`No contract: ${result.error}.`, "error");
      showRaw(text);
      return;
    }
    const yaml = contractYaml(result.doc, { model: data.model, sources: input.sources, timestamp: timestamp(),
      notice: data.yaml_notice });
    log(`Draft contract with ${result.doc.terms.length} terms, every one approved: false.`, "done");
    showResult(input, yaml, result.problems);
  } catch (error) {
    log(`Stopped: ${describe(error)}`, "error");
  } finally {
    state.running = false;
    syncControls();
  }
}

// Sign-in opens a popup, which browsers allow only from the click itself: signIn() is called before any await.
function onExtract() {
  if (state.running || !state.data || !$("ack").checked) return;
  $("log").replaceChildren();
  $("result").hidden = true;
  const input = currentInput();
  if (input.error) {
    log(input.error, "error");
    return;
  }
  if (typeof puter === "undefined") {
    log("Puter.js did not load from js.puter.com, so nothing can be sent.", "error");
    return;
  }
  let signedIn = Promise.resolve();
  if (!puter.auth.isSignedIn()) {
    log("Sign in to Puter in the window that opened (or create an account there)…");
    signedIn = puter.auth.signIn();
  }
  state.running = true;
  syncControls();
  run(input, signedIn);
}

$("extract").addEventListener("click", onExtract);
$("ack").addEventListener("change", syncControls);
$("sample").addEventListener("change", showSample);
for (const radio of document.querySelectorAll("input[name=source]")) radio.addEventListener("change", syncControls);

init().catch((error) => log(`The page could not load its data: ${describe(error)}`, "error"));
