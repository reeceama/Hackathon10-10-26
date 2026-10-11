// Library: everything Referee has captured, the references for what your writing cites (in
// Word or Obsidian), and the proof-of-work report. Checking happens where you write; this
// page is for looking back over your reading.

const STYLE_KEY = "referee-style";

const projectSelect = document.getElementById("project");
const searchBox = document.getElementById("search");
const styleSelect = document.getElementById("citation-style");
const serverStatus = document.getElementById("server");

let sources = [];   // from the server: metadata and passage count per source
let claims = [];    // from the server: verdicts, oldest first
let captures = [];  // from the extension: when each source was read

const get = (path) => chrome.runtime.sendMessage({ type: "get", path });

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function when(ms) {
  return new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function toast(message) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 1600);
}

function style() {
  return Cite.STYLES[styleSelect.value] || Cite.STYLES.apa;
}

// Reading tagged with no project counts towards every project, as it does when checking.
function inProject(project) {
  return !projectSelect.value || project == null || project === projectSelect.value;
}

function supported() {
  return claims.filter((c) => c.label === "supports" && c.source?.url && inProject(c.project));
}

// Cited sources with full metadata, numbered in order of first citation.
function citedSources() {
  const byUrl = new Map(sources.map((s) => [s.url, s]));
  const cited = new Map();
  for (const claim of supported()) {
    if (!cited.has(claim.source.url)) cited.set(claim.source.url, byUrl.get(claim.source.url) || claim.source);
  }
  return [...cited.values()];
}

function renderReferences() {
  const cited = citedSources();
  const numbers = new Map(cited.map((s, i) => [s.url, i + 1]));
  const ordered = style().numbered ? cited : [...cited].sort((a, b) => Cite.sortKey(a).localeCompare(Cite.sortKey(b)));
  const entries = ordered.map((s) => style().reference(s, { number: numbers.get(s.url) }));
  const list = document.getElementById("ref-list");
  list.className = "plain"; // references carry their own [n] where the style is numbered
  list.replaceChildren(...entries.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
  document.getElementById("refs-empty").hidden = entries.length > 0;
  document.getElementById("copy-refs").onclick = async () => {
    await navigator.clipboard.writeText(entries.join("\n"));
    toast(`${entries.length} reference${entries.length === 1 ? "" : "s"} copied`);
  };
}

function renderSources() {
  const query = searchBox.value.trim().toLowerCase();
  const citedCount = new Map();
  for (const claim of supported()) citedCount.set(claim.source.url, (citedCount.get(claim.source.url) || 0) + 1);
  const readAt = new Map(captures.map((c) => [c.url, c.at]));

  const shown = sources
    .filter((s) => inProject(s.project))
    .filter((s) => !query || [s.title, s.site, s.author, s.url].some((v) => String(v || "").toLowerCase().includes(query)))
    .sort((a, b) => (readAt.get(b.url) || 0) - (readAt.get(a.url) || 0));

  document.getElementById("count").textContent = `${shown.length} source${shown.length === 1 ? "" : "s"}`;
  const list = document.getElementById("sources");
  list.replaceChildren(...shown.map((s) => {
    const item = document.createElement("li");
    const n = citedCount.get(s.url) || 0;
    const type = s.type === "pdf" ? "PDF" : s.type === "video" ? "Video" : "Web page";
    const read = readAt.get(s.url) ? when(readAt.get(s.url)) : s.captured_at || "";
    item.innerHTML = `
      <div class="what">
        <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(Cite.cleanTitle(s))}</a>
        <div class="meta">
          <span class="tag">${type}</span>${s.project ? `<span class="tag">${escapeHtml(s.project)}</span>` : ""}
          <span class="tag ${n ? "cited" : ""}">${n ? `Backs ${n} claim${n === 1 ? "" : "s"}` : "Not cited yet"}</span>
          ${escapeHtml([s.site, read].filter(Boolean).join(" · "))}
        </div>
      </div>
      <button class="forget" title="Forget this source">×</button>`;
    item.querySelector(".forget").onclick = async () => {
      await chrome.runtime.sendMessage({ type: "forget", url: s.url });
      toast("Forgotten");
      load();
    };
    return item;
  }));
  if (!shown.length) list.innerHTML = `<li class="hint">${sources.length ? "Nothing matches." : "Nothing captured yet. Read with research mode on, or while writing in Word."}</li>`;
}

// Evidence summary for the writing in this project: what the reading backs and contradicts,
// and whether it leans on one source.
const RELIANCE_SHARE = 0.5;
const RELIANCE_MIN_CLAIMS = 4;

function renderSummary() {
  const mine = claims.filter((c) => inProject(c.project));
  const backed = mine.filter((c) => c.label === "supports");
  const against = mine.length - backed.length;
  const box = document.getElementById("summary");
  if (!mine.length) {
    box.textContent = "";
    return;
  }
  const perSource = new Map();
  for (const c of backed) perSource.set(c.source.url, (perSource.get(c.source.url) || 0) + 1);
  const [topUrl, top] = [...perSource].sort((a, b) => b[1] - a[1])[0] || [];
  const topSource = backed.find((c) => c.source.url === topUrl)?.source;
  box.innerHTML = `<strong>${backed.length} claim${backed.length === 1 ? "" : "s"} backed by your reading</strong>` +
    (against ? ` · ${against} contradicted by a source` : "") +
    (backed.length >= RELIANCE_MIN_CLAIMS && top / backed.length > RELIANCE_SHARE
      ? `<span class="note">${top} of them rest on one source (${escapeHtml(Cite.cleanTitle(topSource))}). Consider backing some with others.</span>` : "");
}

function render() {
  renderSummary();
  renderReferences();
  renderSources();
}

function proofOfWork() {
  // Everything the server holds, timed by the extension's capture log where it has one (the
  // log keeps only recent captures), otherwise by the capture date the server recorded.
  const loggedAt = new Map(captures.map((c) => [c.url, c.at]));
  const read = sources.filter((s) => inProject(s.project))
    .map((s) => ({ url: s.url, title: Cite.cleanTitle(s), at: loggedAt.get(s.url) || Date.parse(s.captured_at || "") || 0 }))
    .sort((a, b) => a.at - b.at);
  const readAt = new Map(read.map((c) => [c.url, c.at]));
  const cited = citedSources();
  const numbers = new Map(cited.map((s, i) => [s.url, i + 1]));
  const byUrl = new Map(sources.map((s) => [s.url, s]));
  const items = supported();
  const name = projectSelect.value || "All reading";

  const readingRows = read.map((c) => `<tr><td>${c.at ? escapeHtml(when(c.at)) : "—"}</td><td>${escapeHtml(c.title || c.url)}<br>
    <span class="url">${escapeHtml(c.url)}</span></td></tr>`).join("");
  const claimRows = items.map((c) => {
    const source = byUrl.get(c.source.url) || c.source;
    const cite = style().inText(source, { number: numbers.get(c.source.url), page: c.page, time: c.time });
    const at = readAt.get(c.source.url);
    return `<tr><td>${escapeHtml(c.sentence)}</td><td>${escapeHtml(cite)}<br><q>${escapeHtml(c.quote || "")}</q></td>
      <td>${at ? escapeHtml(when(at)) : "—"}</td><td>${escapeHtml(when(c.at * 1000))}</td></tr>`;
  }).join("");

  const html = `<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<title>Proof of work: ${escapeHtml(name)}</title>
<style>
  :root { --text: #1f2328; --muted: #6b7280; --line: #e5e7eb; --page: #ffffff; }
  @media (prefers-color-scheme: dark) { :root { --text: #e6e6e6; --muted: #9aa0a6; --line: #30363d; --page: #0d1117; } }
  @media print { :root { --text: #1f2328; --muted: #6b7280; --line: #e5e7eb; --page: #ffffff; } }  /* paper stays light */
  body { font: 14px/1.5 Georgia, serif; color: var(--text); background: var(--page); max-width: 920px; margin: 32px auto; padding: 0 20px; }
  h1 { font-size: 22px; margin-bottom: 4px; } h2 { font-size: 16px; margin-top: 28px; }
  .meta, .url, .note { color: var(--muted); font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; vertical-align: top; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
</style></head><body>
<h1>Proof of work: ${escapeHtml(name)}</h1>
<div class="meta">Generated by Referee on ${escapeHtml(when(Date.now()))} · ${read.length} source${read.length === 1 ? "" : "s"} read · ${items.length} supported claim${items.length === 1 ? "" : "s"}</div>
<h2>Reading log</h2>
${read.length ? `<table><tr><th>Read</th><th>Source</th></tr>${readingRows}</table>` : "<p>No reading has been recorded.</p>"}
<h2>Claims and their evidence</h2>
${items.length ? `<table><tr><th>Claim</th><th>Source and supporting passage</th><th>Source read</th><th>Claim checked</th></tr>${claimRows}</table>` : "<p>No supported claims yet.</p>"}
<p class="note">Reading times were recorded by the Referee browser extension when each source was captured, and claims
when Referee checked them as they were written. Both are kept on this computer. This report shows the research behind
the writing; it is not tamper-proof.</p>
<p class="note">To keep a copy, print this page (Cmd+P or Ctrl+P) and choose "Save as PDF".</p>
</body></html>`;
  window.open(URL.createObjectURL(new Blob([html], { type: "text/html" })), "_blank");
}

async function load() {
  const [fetchedSources, fetchedClaims, stored] = await Promise.all([
    get("sources"), get("claims"), chrome.storage.local.get("captures"),
  ]);
  const online = Array.isArray(fetchedSources);
  serverStatus.dataset.state = online ? "online" : "offline";
  serverStatus.textContent = online ? "" : "Server not running";
  sources = online ? fetchedSources : [];
  claims = Array.isArray(fetchedClaims) ? fetchedClaims : [];
  captures = stored.captures || [];

  const projects = [...new Set(sources.map((s) => s.project).filter(Boolean))].sort();
  const current = projectSelect.value;
  projectSelect.replaceChildren(new Option("All reading", ""), ...projects.map((p) => new Option(p, p)));
  projectSelect.value = projects.includes(current) ? current : "";
  render();
}

try { styleSelect.value = localStorage.getItem(STYLE_KEY) || "apa"; } catch { /* storage blocked */ }
styleSelect.onchange = () => {
  try { localStorage.setItem(STYLE_KEY, styleSelect.value); } catch { /* storage blocked */ }
  render();
};
projectSelect.onchange = render;
searchBox.oninput = renderSources;
document.getElementById("proof").onclick = proofOfWork;
chrome.storage.onChanged.addListener((changes, area) => { if (area === "local" && changes.captures) load(); });
load();
