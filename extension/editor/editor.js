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
let pauseTimer;

// Inside the extension, requests go through the background worker; opened as a plain
// file (for testing), the editor calls the backend directly.
async function api(type, body) {
  if (IN_EXTENSION) return chrome.runtime.sendMessage({ type, body });
  const response = await fetch(`${SERVER}/${type}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  renderCards(matched, items);
  renderSummary(matched);
}

function renderCards(matched, items) {
  cardsBox.innerHTML = "";
  emptyHint.hidden = matched.length > 0;
  for (const item of matched) {
    const { sentence, entry } = item;
    const match = entry.match;
    const index = items.indexOf(item);
    const source = match.source || {};
    const year = source.date ? ` · ${String(source.date).slice(0, 4)}` : "";

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
      <div class="source"><a href="${escapeHtml(source.url || "#")}" target="_blank" rel="noopener">${escapeHtml(source.title || "Source")}</a>${escapeHtml(year)}</div>
      ${warnings.map((w) => `<div class="warning">${escapeHtml(w)}</div>`).join("")}
    `;

    card.querySelector(".dismiss").addEventListener("click", () => {
      dismissed.add(sentence);
      sendFeedback("dismissed", sentence, match);
      render();
    });
    card.querySelector(".source a").addEventListener("click", () => sendFeedback("opened_source", sentence, match));

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
  banner.classList.toggle("off", !state.research);
  const topic = title.value.trim() || "your essay";
  bannerText.textContent = state.research ? `Researching for: ${topic}` : "Research mode is off";
  bannerButton.textContent = state.research ? "Stop" : "Start";
}

bannerButton.addEventListener("click", async () => {
  const state = await researchState();
  setResearch(!state.research);
});

if (IN_EXTENSION) chrome.storage.onChanged.addListener(showResearch);

(async () => {
  loadDraft();
  const state = await researchState();
  if (IN_EXTENSION && !state.research && (state.mode ?? "manual") === "auto") await setResearch(true);
  showResearch();
  render();
  checkNewSentences();
})();
