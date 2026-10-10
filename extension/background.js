// Background service worker: talks to the backend, runs research mode and keeps a log of
// captured pages for the popup. Pages and the editor send messages here rather than calling
// localhost themselves, which Chrome would block from ordinary web pages.

importScripts("skip.js");

const SERVER = "http://localhost:8000";
const HEADERS = { "Content-Type": "application/json", "X-Referee": "1" };
const ROUTES = ["check", "feedback"];
const MAX_LOG = 50;

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (ROUTES.includes(message.type)) {
    post(message.type, message.body).then(reply).catch((error) => reply({ error: String(error) }));
    return true; // reply asynchronously
  }
  if (message.type === "capture") {
    capture(message.body).then(reply);
    return true;
  }
  if (message.type === "forget") {
    forgetOne(message.url).then(reply);
    return true;
  }
  if (message.type === "expire") {
    expireOldReading().then(reply);
    return true;
  }
  if (message.type === "clear") {
    forgetEverything().then(reply);
    return true;
  }
  if (message.type === "server") {
    fetch(`${SERVER}/`, { headers: HEADERS, cache: "no-store" })
      .then((response) => reply(response.ok))
      .catch(() => reply(false));
    return true;
  }
  if (message.type === "writing-ping") {
    fetch(`${SERVER}/writing`, { method: "POST", headers: HEADERS })
      .then(() => reply({ ok: true }))
      .catch(() => reply({ ok: false }));
    return true;
  }
  if (message.type === "writing") {
    fetch(`${SERVER}/writing`, { headers: HEADERS })
      .then((response) => response.json())
      .then((result) => reply(Boolean(result.active)))
      .catch(() => reply(false));
    return true;
  }
  if (message.type === "setResearch") {
    setResearch(message.on, message.minutes).then(() => reply({ ok: true }));
    return true;
  }
});

async function post(route, body) {
  const response = await fetch(`${SERVER}/${route}`, { method: "POST", headers: HEADERS, body: JSON.stringify(body) });
  return response.json();
}

// Sends a page to the backend and records what happened, for the popup's saved pages list.
async function capture({ url, title, html }) {
  const { project = "" } = await chrome.storage.local.get("project");
  let entry = { url, title: title || url, at: Date.now(), project: project || null };
  try {
    const result = await post("capture", { url, html, project });
    if (result.ok && result.already_captured) entry.status = "already";
    else if (result.ok) entry = { ...entry, status: "saved", passages: result.passages };
    else entry = { ...entry, status: "skipped", reason: result.reason };
  } catch {
    entry = { ...entry, status: "offline", reason: "the Referee server isn't running" };
  }
  console.log("[Referee] capture:", entry);
  await logCapture(entry);
  return entry;
}

async function logCapture(entry) {
  const { captures = [] } = await chrome.storage.local.get("captures");
  const previous = captures.find((c) => c.url === entry.url);
  // A repeat visit shouldn't overwrite the original "saved" record.
  const keep = entry.status === "already" && previous ? previous : entry;
  const rest = captures.filter((c) => c.url !== entry.url);
  await chrome.storage.local.set({ captures: [keep, ...rest].slice(0, MAX_LOG) });
}

// --- PDFs ---
// Chrome's PDF viewer doesn't run extension scripts, so PDF tabs are watched from here.
// A PDF counts as read once its tab has been showing for READ_MS, as for web pages.

const READ_MS = 20000;
const MAX_PDF_BYTES = 25 * 1024 * 1024;
const PDF_URL = /\.pdf($|[?#])/i;
const pdfTimers = new Map(); // tab id -> timer
const pdfsSent = new Set();  // URLs already sent this session

// Research mode on, or (automatic mode only) the Word add-in reports someone writing.
async function capturing() {
  const { research, mode } = await chrome.storage.local.get(["research", "mode"]);
  if (research) return true;
  if ((mode ?? "auto") !== "auto") return false;
  try {
    const result = await fetch(`${SERVER}/writing`, { headers: HEADERS }).then((r) => r.json());
    return Boolean(result.active);
  } catch {
    return false;
  }
}

function watchPdf(tab) {
  if (!tab.url || !PDF_URL.test(tab.url) || pdfsSent.has(tab.url) || isSkipped(tab.url)) return;
  clearTimeout(pdfTimers.get(tab.id));
  pdfTimers.set(tab.id, setTimeout(async () => {
    pdfTimers.delete(tab.id);
    const current = await chrome.tabs.get(tab.id).catch(() => null);
    // Only if the same PDF is still the tab being looked at.
    if (current?.active && current.url === tab.url) capturePdf(current.url, current.title);
  }, READ_MS));
}

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status === "complete") watchPdf(tab);
});
chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then(watchPdf).catch(() => {});
});
chrome.tabs.onRemoved.addListener((tabId) => {
  clearTimeout(pdfTimers.get(tabId));
  pdfTimers.delete(tabId);
});

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

// Downloads the PDF the person is reading (with their own login, so journal papers they
// can open are included) and sends it to the backend.
async function capturePdf(url, title) {
  if (!(await capturing())) return;
  pdfsSent.add(url);
  const { project = "" } = await chrome.storage.local.get("project");
  let entry = { url, title: title || url, at: Date.now(), project: project || null };
  try {
    const response = await fetch(url, { credentials: "include" });
    const type = response.headers.get("content-type") || "";
    if (!url.startsWith("file:") && !type.includes("pdf")) throw new Error("not a PDF");
    const data = await response.arrayBuffer();
    if (data.byteLength > MAX_PDF_BYTES) throw new Error("PDF is larger than 25 MB");
    const result = await post("capture-pdf", { url, title: title || "", project, data: toBase64(data) });
    if (result.ok && result.already_captured) entry.status = "already";
    else if (result.ok) entry = { ...entry, status: "saved", passages: result.passages };
    else entry = { ...entry, status: "skipped", reason: result.reason };
  } catch (error) {
    const offline = String(error).includes("Failed to fetch") && url.startsWith("file:");
    entry = { ...entry, status: "skipped", reason: offline ? "allow access to file URLs in Chrome's extension settings" : String(error.message || error) };
  }
  console.log("[Referee] PDF capture:", entry);
  await logCapture(entry);
}

// Forget one page or PDF, on the server and in the saved pages list.
async function forgetOne(url) {
  try {
    await fetch(`${SERVER}/sources?url=${encodeURIComponent(url)}`, { method: "DELETE", headers: HEADERS });
  } catch {
    // Server down: the list still drops it; the server copy goes next time it's forgotten.
  }
  const { captures = [] } = await chrome.storage.local.get("captures");
  await chrome.storage.local.set({ captures: captures.filter((c) => c.url !== url) });
  pdfsSent.delete(url);
  return { ok: true };
}

// Reading older than the chosen number of days is forgotten automatically (checked daily).
async function expireOldReading() {
  const { expiryDays = "0", captures = [] } = await chrome.storage.local.get(["expiryDays", "captures"]);
  const days = Number(expiryDays);
  if (!days) return { ok: true, forgotten: 0 };
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  const old = captures.filter((c) => c.at < cutoff);
  for (const c of old) await forgetOne(c.url);
  return { ok: true, forgotten: old.length };
}

chrome.alarms.create("expire-reading", { periodInMinutes: 24 * 60 });

// Forget everything captured, on the server and in the saved pages list.
async function forgetEverything() {
  try {
    await post("clear", {});
  } catch {
    // Server down: still clear the list so the popup matches what the person expects.
  }
  await chrome.storage.local.set({ captures: [] });
  return { ok: true };
}

// Research mode: on/off, with an optional timer that switches it off automatically.
async function setResearch(on, minutes) {
  const until = on && minutes ? Date.now() + minutes * 60 * 1000 : null;
  await chrome.storage.local.set({ research: on, until });
  await chrome.alarms.clear("research-off");
  if (until) chrome.alarms.create("research-off", { when: until });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "research-off") setResearch(false);
  if (alarm.name === "expire-reading") expireOldReading();
});

// While research mode is on, the badge shows how many pages have been saved.
async function updateBadge() {
  const { research, captures = [] } = await chrome.storage.local.get(["research", "captures"]);
  const saved = captures.filter((c) => c.status === "saved").length;
  await chrome.action.setBadgeBackgroundColor({ color: "#111111" });
  await chrome.action.setBadgeText({ text: research ? String(saved || "ON") : "" });
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes.research || changes.captures)) updateBadge();
});
chrome.runtime.onStartup.addListener(updateBadge);
chrome.runtime.onStartup.addListener(expireOldReading);
chrome.runtime.onInstalled.addListener(updateBadge);
