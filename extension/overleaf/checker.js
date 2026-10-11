// Referee in Overleaf: checks each finished sentence of the open file against your reading, as the
// Word helper does in Word, and lists what it finds in a small panel. Overleaf's text is never
// edited; supporting sources come with a \cite{} to copy instead.
//
// For a sentence that already cites something, it says whether the cited paper is the one your
// reading says backs it up.

(() => {
  const PAUSE = 3000;            // ms after the last change before checking
  const project = location.pathname.split("/")[2] || "overleaf";
  const memory = `overleaf:${project}`;
  let results = {};              // sentence -> {keys, result}
  let keysByUrl = {};
  let timer = null;
  let running = false;
  let latest = "";

  const ask = (message) => new Promise((resolve) => {
    try { chrome.runtime.sendMessage(message, (reply) => resolve(chrome.runtime.lastError ? null : reply)); }
    catch { resolve(null); } // the extension was reloaded: this page's script is stale
  });

  chrome.storage.local.get(memory, (saved) => { results = saved[memory] || {}; render(); });

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.referee !== "overleaf") return;
    latest = event.data.text;
    clearTimeout(timer);
    timer = setTimeout(checkAll, PAUSE);
  });

  async function loadKeys() {
    const sources = await ask({ type: "get", path: "sources" });
    if (Array.isArray(sources)) keysByUrl = Object.fromEntries(sources.map((s) => [s.url, s.cite_key]));
  }

  async function checkAll() {
    if (running) { timer = setTimeout(checkAll, PAUSE); return; }
    running = true;
    const found = Latex.sentences(latest);
    const fresh = found.filter(({ sentence }) => !results[sentence]);
    if (fresh.length) await loadKeys();
    for (const { sentence, keys } of fresh) {
      const result = await ask({ type: "check", body: { sentence, document: `${document.title.replace(/ - Overleaf.*$/, "")} (Overleaf)` } });
      if (!result || result.error) break;  // server not running: try again after the next change
      results[sentence] = { keys, result };
      render(found);
    }
    // Forget sentences that are no longer in the file, so the panel matches what's written.
    const present = new Set(found.map((f) => f.sentence));
    for (const sentence of Object.keys(results)) if (!present.has(sentence)) delete results[sentence];
    for (const { sentence, keys } of found) if (results[sentence]) results[sentence].keys = keys;
    chrome.storage.local.set({ [memory]: results });
    running = false;
    render(found);
  }

  const title = (source) => (source?.title || source?.url || "a source").replace(/\s+[-|–—]\s+[^-|–—]+$/, "");

  // What a checked sentence needs telling, if anything: [kind, message, key to copy].
  function findings(keys, result) {
    const out = [];
    if (!result.match) {
      if (result.needs_source && !keys.length) {
        const closest = (result.closest || []).map(title).join("; ");
        out.push(["warn", `Reads like a claim that needs a citation, but nothing you've read supports it.${closest ? ` Closest: ${closest}.` : ""}`, null, result.search]);
      }
      return out;
    }
    const source = result.source || {};
    const key = keysByUrl[source.url];
    if (source.retracted) out.push(["bad", `${title(source)} has been retracted.`]);
    if (result.label === "contradicts") out.push(["bad", `Your source says otherwise: “${result.quote}” (${title(source)})`]);
    if (result.label === "supports") {
      if (!keys.length) out.push(["good", `Supported by ${title(source)}. Cite it:`, key]);
      else if (key && !keys.includes(key)) out.push(["warn", `You cite ${keys.join(", ")}, but the reading that supports this is ${title(source)}.`, key]);
      else out.push(["good", `Supported by ${title(source)}${keys.length ? ", which you cite" : ""}.`]);
    }
    if (result.misquote) out.push(["warn", `This quotation doesn't match the source. It says: “${result.quote}”`]);
    if (result.too_close) out.push(["warn", "Very close to the source's wording. Consider quoting or rephrasing."]);
    for (const figure of result.wrong_numbers || []) out.push(["warn", `“${figure}” doesn't appear in the source.`]);
    if (result.together_with) out.push(["warn", `Combines two sources: also cite ${title(result.together_with.source)}.`, keysByUrl[result.together_with.source?.url]]);
    if (result.mixed) out.push(["warn", `Mixed evidence: ${title(result.mixed)} points the other way.`]);
    return out;
  }

  // The panel, in a shadow root so Overleaf's styles and Referee's can't affect each other.
  const host = document.createElement("div");
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `<style>
    .box { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; width: 340px; max-height: 50vh; display: flex; flex-direction: column;
      font: 13px -apple-system, system-ui, sans-serif; color: #1d1d1f; background: #fff; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,.2); }
    header { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; font-weight: 600; cursor: pointer; }
    .list { overflow-y: auto; padding: 0 12px 10px; }
    .closed .list { display: none; }
    .item { padding: 8px 0; border-top: 1px solid #eee; }
    .sentence { color: #6e6e73; font-size: 12px; margin-bottom: 4px; }
    .note { padding-left: 8px; border-left: 3px solid; margin-top: 4px; }
    .good { border-color: #34c759; } .warn { border-color: #ff9f0a; } .bad { border-color: #ff3b30; }
    button, a { font: inherit; font-size: 12px; margin-left: 4px; }
    code { font-size: 12px; background: #f2f2f7; padding: 1px 4px; border-radius: 4px; }
    @media (prefers-color-scheme: dark) { .box { background: #2c2c2e; color: #f5f5f7; } .item { border-color: #3a3a3c; } code { background: #3a3a3c; } }
  </style><div class="box closed"><header><span>Referee</span><span class="count"></span></header><div class="list"></div></div>`;
  document.documentElement.append(host);
  const box = shadow.querySelector(".box");
  shadow.querySelector("header").addEventListener("click", () => box.classList.toggle("closed"));

  function render(found) {
    const order = found ? found.map((f) => f.sentence) : Object.keys(results);
    const items = order.filter((s) => results[s]).map((s) => [s, findings(results[s].keys, results[s].result)]).filter(([, f]) => f.length);
    const problems = items.filter(([, f]) => f.some(([kind]) => kind !== "good")).length;
    shadow.querySelector(".count").textContent = running ? "checking…" : items.length ? `${problems} to look at, ${items.length - problems} fine` : "nothing yet";
    const list = shadow.querySelector(".list");
    list.replaceChildren(...items.map(([sentence, notes]) => {
      const item = document.createElement("div");
      item.className = "item";
      const quoted = document.createElement("div");
      quoted.className = "sentence";
      quoted.textContent = sentence.length > 120 ? `${sentence.slice(0, 117)}…` : sentence;
      item.append(quoted);
      for (const [kind, message, key, search] of notes) {
        const note = document.createElement("div");
        note.className = `note ${kind}`;
        note.textContent = message;
        if (key) {
          const cite = `\\cite{${key}}`;
          const code = document.createElement("code");
          code.textContent = cite;
          const copy = document.createElement("button");
          copy.textContent = "Copy";
          copy.addEventListener("click", () => navigator.clipboard.writeText(cite).then(() => { copy.textContent = "Copied"; }));
          note.append(" ", code, copy);
        }
        if (search) {
          const link = document.createElement("a");
          link.href = search; link.target = "_blank"; link.textContent = "Search Scholar";
          note.append(link);
        }
        item.append(note);
      }
      return item;
    }));
  }
})();
