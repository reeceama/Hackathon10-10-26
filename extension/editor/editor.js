// Editor: checks each finished sentence against the backend and shows the results as
// highlights in the text and cards in the margin. Dismissing a card or opening its
// source is reported to /feedback, so the backend learns what this person finds useful.

const SERVER = "http://localhost:8000";
const IN_EXTENSION = typeof chrome !== "undefined" && Boolean(chrome.runtime?.id);
const MIN_WORDS = 5;
const PAUSE_MS = 800;
const SENTENCE = /[^.!?]+[.!?]+["”’)\]]*/g;
const LABELS = { supports: "Supported", contradicts: "Your source says otherwise", misquote: "Misquote" };

const editor = document.getElementById("editor");
const backdrop = document.getElementById("backdrop");
const cardsBox = document.getElementById("cards");
const emptyHint = document.getElementById("empty");
const summary = document.getElementById("summary");
const title = document.getElementById("title");

const checks = new Map(); // sentence -> { state: "pending" | "done", match }
const dismissed = new Set();
let citationStyle = "apa"; // apa | harvard | ieee | ams, saved in the browser

function style() {
  return Cite.STYLES[citationStyle] || Cite.STYLES.apa;
}

const sourceKey = (source) => source.url || Cite.cleanTitle(source);

// Numbered styles count sources in order of first citation in the text.
function sourceNumbers(matched) {
  const numbers = new Map();
  for (const { entry } of matched) {
    if (entry.match.label !== "supports" || !entry.match.source) continue;
    const key = sourceKey(entry.match.source);
    if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
  }
  return numbers;
}

function citationFor(match, numbers) {
  return style().inText(match.source, { number: numbers.get(sourceKey(match.source)), page: match.page });
}
let pauseTimer;

// Inside the extension, requests go through the background worker; opened as a plain
// file (for testing), the editor calls the backend directly.
async function api(type, body) {
  if (IN_EXTENSION) return chrome.runtime.sendMessage({ type, body });
  const response = await fetch(`${SERVER}/${type}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Referee": "1" },
    body: JSON.stringify(body),
  });
  return response.json();
}

function finishedSentences(text) {
  return (text.match(SENTENCE) || [])
    .map((s) => s.trim())
    .filter((s) => s.split(/\s+/).length >= MIN_WORDS);
}

// Checking is separate from research mode: research mode controls what is captured,
// but anything already captured can be checked against at any time. A sentence is only
// sent to Claude when the local search finds a closely matching passage.
let retryTimer;

async function checkNewSentences() {
  for (const sentence of finishedSentences(editor.value)) {
    if (checks.has(sentence)) continue;
    checks.set(sentence, { state: "pending" });
    api("check", { sentence })
      .then((result) => {
        if (!result || result.error) throw new Error(result?.error || "No reply from the server");
        checks.set(sentence, { state: "done", match: result.match ? result : null });
      })
      .catch(() => {
        // Server unreachable: forget this attempt so the sentence is checked again shortly.
        checks.delete(sentence);
        clearTimeout(retryTimer);
        retryTimer = setTimeout(checkNewSentences, 5000);
      })
      .finally(render);
  }
  render();
}

function sendFeedback(event, sentence, match) {
  api("feedback", {
    event,
    sentence,
    url: match.source?.url || "",
    label: match.label,
    confidence: match.confidence,
    score: match.score || 0,
  }).catch(() => {});
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function markClass(entry) {
  if (entry.state === "pending") return "pending";
  const { label, misquote, too_close } = entry.match;
  return label === "supports" && (misquote || too_close) ? "supports warn" : label;
}

// Sentences to highlight, in document order, without overlaps.
function highlights() {
  const text = editor.value;
  const found = [];
  for (const [sentence, entry] of checks) {
    if (dismissed.has(sentence)) continue;
    if (entry.state === "done" && !entry.match) continue;
    const start = text.indexOf(sentence);
    if (start !== -1) found.push({ sentence, entry, start, end: start + sentence.length });
  }
  found.sort((a, b) => a.start - b.start);
  return found.filter((item, i) => i === 0 || item.start >= found[i - 1].end);
}

function render() {
  const text = editor.value;
  const items = highlights();

  let html = "";
  let position = 0;
  items.forEach((item, i) => {
    html += escapeHtml(text.slice(position, item.start));
    html += `<mark class="${markClass(item.entry)}" data-index="${i}">${escapeHtml(item.sentence)}</mark>`;
    position = item.end;
  });
  backdrop.innerHTML = html + escapeHtml(text.slice(position)) + "\n";
  growEditor();

  const matched = items.filter((item) => item.entry.state === "done");
  const numbers = sourceNumbers(matched);
  renderCards(matched, items, numbers);
  renderSummary(matched);
  renderReferences(matched, numbers);
}

// Reference list for every source that supports a sentence: alphabetical for author-date
// styles, in order of first citation for numbered ones.
function renderReferences(matched, numbers) {
  const sources = new Map();
  for (const { entry } of matched) {
    const source = entry.match.source;
    if (entry.match.label === "supports" && source) sources.set(sourceKey(source), source);
  }
  const ordered = [...sources.values()].sort(style().numbered
    ? (a, b) => numbers.get(sourceKey(a)) - numbers.get(sourceKey(b))
    : (a, b) => Cite.sortKey(a).localeCompare(Cite.sortKey(b)));
  const entries = ordered.map((source) => style().reference(source, { number: numbers.get(sourceKey(source)) }));
  document.getElementById("refs").hidden = entries.length === 0;
  document.getElementById("ref-list").replaceChildren(...entries.map((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
  document.getElementById("copy-refs").onclick = () => copyText(
    entries.join("\n"), `${entries.length} reference${entries.length === 1 ? "" : "s"} copied`);
}

// A link that opens the source scrolled to, and highlighting, the quoted passage (Chrome).
function textFragmentUrl(url, quote) {
  if (!quote) return url;
  const words = quote.replace(/\s+/g, " ").trim().split(" ");
  const encode = (text) => encodeURIComponent(text).replace(/-/g, "%2D");
  const fragment = words.length > 10
    ? `${encode(words.slice(0, 4).join(" "))},${encode(words.slice(-4).join(" "))}`
    : encode(words.join(" "));
  return `${url.split("#")[0]}#:~:text=${fragment}`;
}

let toastTimer;
async function copyText(text, message) {
  const toast = document.getElementById("toast");
  try {
    await navigator.clipboard.writeText(text);
    toast.textContent = message;
  } catch {
    toast.textContent = "Couldn't copy. Select the text and copy it instead.";
  }
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
}

function renderCards(matched, items, numbers) {
  cardsBox.innerHTML = "";
  emptyHint.hidden = matched.length > 0;
  for (const item of matched) {
    const { sentence, entry } = item;
    const match = entry.match;
    const index = items.indexOf(item);
    const source = match.source || {};
    const year = (source.date ? ` · ${String(source.date).slice(0, 4)}` : "") + (match.page ? ` · p. ${match.page}` : "");

    const warnings = [];
    if (match.misquote && match.label !== "misquote") warnings.push("This quotation doesn't match the source exactly.");
    if (match.too_close) warnings.push("Very close to the source's wording. Consider quoting it or rephrasing.");

    const card = document.createElement("div");
    card.className = `card ${match.label}`;
    card.innerHTML = `
      <button class="dismiss" title="Not useful">×</button>
      <div class="label">${LABELS[match.label] || match.label}</div>
      <div class="sentence">${escapeHtml(sentence.length > 90 ? sentence.slice(0, 90) + "…" : sentence)}</div>
      <blockquote class="quote">“${escapeHtml(match.quote || "")}”</blockquote>
      <div class="source">${escapeHtml(Cite.cleanTitle(source))}${escapeHtml(year)}</div>
      ${warnings.map((w) => `<div class="warning">${escapeHtml(w)}</div>`).join("")}
      <div class="actions">
        ${match.label === "supports" ? `<button class="copy-citation">Copy ${escapeHtml(citationFor(match, numbers))}</button>` : ""}
        ${source.url ? `<a class="open-source" href="${escapeHtml(textFragmentUrl(source.url, match.quote))}" target="_blank" rel="noopener">Open source</a>` : ""}
      </div>
    `;

    card.querySelector(".dismiss").addEventListener("click", () => {
      dismissed.add(sentence);
      sendFeedback("dismissed", sentence, match);
      render();
    });
    card.querySelector(".open-source")?.addEventListener("click", () => sendFeedback("opened_source", sentence, match));
    card.querySelector(".copy-citation")?.addEventListener("click", () => copyText(citationFor(match, numbers), "Citation copied"));

    const mark = () => backdrop.querySelector(`mark[data-index="${index}"]`);
    card.addEventListener("mouseenter", () => mark()?.classList.add("active"));
    card.addEventListener("mouseleave", () => mark()?.classList.remove("active"));
    cardsBox.appendChild(card);
  }
}

function renderSummary(matched) {
  const count = (label) => matched.filter((item) => item.entry.match.label === label).length;
  const warnings = matched.filter((item) => item.entry.match.misquote || item.entry.match.too_close).length;
  const pending = [...checks.values()].filter((entry) => entry.state === "pending").length;
  const parts = [`${count("supports")} supported`, `${count("contradicts")} contradicted`, `${warnings} wording warning${warnings === 1 ? "" : "s"}`];
  summary.textContent = parts.join(" · ") + (pending ? ` · checking ${pending}…` : "");
}

editor.addEventListener("input", () => {
  signalWriting();
  saveDraft();
  render();
  clearTimeout(pauseTimer);
  // Check straight away at the end of a sentence, otherwise after a short pause.
  if (/[.!?]["”’)\]]*\s*$/.test(editor.value)) checkNewSentences();
  else pauseTimer = setTimeout(checkNewSentences, PAUSE_MS);
});
window.addEventListener("resize", growEditor);

function growEditor() {
  editor.style.height = "auto";
  editor.style.height = `${editor.scrollHeight}px`;
}
title.addEventListener("input", () => {
  saveDraft();
  showResearch();
});

// Drafts are a convenience only: kept in this browser, never sent anywhere.
function saveDraft() {
  try {
    localStorage.setItem("referee-draft", JSON.stringify({ title: title.value, text: editor.value }));
  } catch {}
}

function loadDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem("referee-draft") || "null");
    if (draft) {
      title.value = draft.title || "";
      editor.value = draft.text || "";
    }
  } catch {}
}

// Research mode banner: in automatic mode, opening the editor switches it on.
const banner = document.getElementById("research-banner");
const bannerText = document.getElementById("research-text");
const bannerButton = document.getElementById("research-toggle");

async function researchState() {
  if (!IN_EXTENSION) return { research: true };
  return chrome.storage.local.get(["research", "until", "mode", "duration"]);
}

async function setResearch(on) {
  if (!IN_EXTENSION) return;
  const { duration } = await chrome.storage.local.get("duration");
  await chrome.runtime.sendMessage({ type: "setResearch", on, minutes: Number(duration ?? 60) });
  showResearch();
}

async function showResearch() {
  const state = await researchState();
  const automatic = !state.research && (state.mode ?? "auto") === "auto";
  banner.classList.toggle("off", !state.research && !automatic);
  const topic = title.value.trim() || "your writing";
  if (state.research) bannerText.textContent = `Researching for: ${topic}`;
  else if (automatic) bannerText.textContent = "Capturing your reading while you write";
  else bannerText.textContent = "Research mode is off";
  bannerButton.textContent = state.research ? "Stop" : "Start";
}

// In automatic mode, Referee captures reading only while someone is writing - here, in
// Word or in Obsidian. Typing here tells the backend so (at most once a minute); capture
// stops a few minutes after the typing does.
let lastSignal = 0;
function signalWriting() {
  if (!IN_EXTENSION || Date.now() - lastSignal < 60 * 1000) return;
  lastSignal = Date.now();
  chrome.runtime.sendMessage({ type: "writing-ping" }).catch(() => {});
}

bannerButton.addEventListener("click", async () => {
  const state = await researchState();
  setResearch(!state.research);
});

if (IN_EXTENSION) chrome.storage.onChanged.addListener(showResearch);

// Newly captured reading can make a sentence citable that had no source before.
if (IN_EXTENSION) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes.captures) return;
    for (const [sentence, entry] of checks) if (entry.state === "done" && !entry.match) checks.delete(sentence);
    checkNewSentences();
  });
}

const serverStatus = document.getElementById("server");
async function showServer() {
  const online = IN_EXTENSION
    ? await chrome.runtime.sendMessage({ type: "server" })
    : await fetch(`${SERVER}/`).then((r) => r.ok).catch(() => false);
  serverStatus.dataset.state = online ? "online" : "offline";
  serverStatus.textContent = online ? "" : "Server not running. Start it with: uvicorn main:app";
}

const styleMenu = document.getElementById("citation-style");
styleMenu.addEventListener("change", () => {
  citationStyle = styleMenu.value;
  try { localStorage.setItem("referee-style", citationStyle); } catch {}
  render();
});

(async () => {
  try { citationStyle = localStorage.getItem("referee-style") || "apa"; } catch {}
  styleMenu.value = citationStyle;
  loadDraft();
  showResearch();
  render();
  checkNewSentences();
  showServer();
  setInterval(showServer, 15000);
})();
