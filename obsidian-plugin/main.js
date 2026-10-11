// Referee for Obsidian: checks the open note against the reading captured by the browser
// extension, and tells the server you're writing so the extension captures in automatic mode.
// Plain JavaScript, so it runs without a build step.

const { Plugin, ItemView, PluginSettingTab, Setting, MarkdownView, Notice, requestUrl } = require("obsidian");

const VIEW = "referee-view";
const DEFAULTS = { server: "http://localhost:8000", project: "" };
const PING_EVERY = 60 * 1000;  // the server treats a ping as "writing" for five minutes
const PAUSE_MS = 1500;         // check after this long without typing
const MIN_WORDS = 5;
const OLD_SOURCE_YEARS = 10;
const LABELS = { supports: "Supported", contradicts: "Your source says otherwise", misquote: "Misquote" };

function sentences(text) {
  return text
    .replace(/^---[\s\S]*?---/, "")         // front matter
    .replace(/```[\s\S]*?```/g, "")         // code blocks
    .split(/(?<=[.!?])["”’)\]]*\s+/)
    .map((s) => s.replace(/^[#>*\-\s]+/, "").trim())
    .filter((s) => /[.!?]["”’)\]]*$/.test(s) && s.split(/\s+/).length >= MIN_WORDS);
}

function year(source) {
  return parseInt(String(source?.date || ""), 10) || null;
}

function inText(source) {
  const surname = String(source?.author || "").split(/[,;]| and /)[0].trim().split(/\s+/).pop();
  return `(${surname || source?.site || source?.title || "Source"}, ${year(source) || "n.d."})`;
}

class RefereeView extends ItemView {

  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType() { return VIEW; }
  getDisplayText() { return "Referee"; }
  getIcon() { return "check-circle"; }

  async onOpen() { this.draw(); }

  draw() {
    const box = this.containerEl.children[1];
    box.empty();
    const results = this.plugin.results();
    const shown = results.filter(([, r]) => r.match || r.needs_source);
    const pending = results.filter(([, r]) => r.pending).length;
    box.createDiv({ cls: "referee-summary", text: shown.length || pending
      ? `${shown.filter(([, r]) => r.match?.label === "supports").length} supported · ${shown.filter(([, r]) => !r.match).length} need a source${pending ? ` · checking ${pending}…` : ""}`
      : "Write a few sentences. Claims your reading backs or contradicts will appear here." });

    for (const [sentence, r] of shown) {
      const m = r.match;
      const card = box.createDiv({ cls: `referee-card ${m ? m.label : "needs"}` });
      card.createDiv({ cls: "referee-label", text: m ? LABELS[m.label] || m.label : "Needs a source" });
      card.createDiv({ cls: "referee-sentence", text: sentence.length > 90 ? sentence.slice(0, 90) + "…" : sentence });
      if (!m) {
        card.createDiv({ cls: "referee-sentence", text: "This reads like a factual claim, but nothing you've read supports it yet." });
        if (r.closest?.length) card.createDiv({ text: `Closest in your reading: ${r.closest.map((c) => c.title || c.url).join("; ")}` });
        continue;
      }
      card.createDiv({ cls: "referee-quote", text: `“${m.quote}”` });
      card.createDiv({ text: `${m.source?.title || m.source?.url || ""}${year(m.source) ? ` · ${year(m.source)}` : ""}` });
      if (m.misquote && m.label !== "misquote") card.createDiv({ cls: "referee-warning", text: "This quotation doesn't match the source exactly." });
      if (m.too_close) card.createDiv({ cls: "referee-warning", text: "Very close to the source's wording. Consider quoting it or rephrasing." });
      for (const c of (m.changes || []).slice(0, 3)) {
        card.createDiv({ cls: "referee-warning", text: c.wrote && c.source ? `You quoted “${c.wrote}”; the source says “${c.source}”.`
          : c.wrote ? `“${c.wrote}” isn't in the source's wording.` : `You left out “${c.source}”.` });
      }
      for (const n of m.wrong_numbers || []) card.createDiv({ cls: "referee-warning", text: `“${n}” doesn't appear in the source. Check the figure.` });
      if (m.together_with) card.createDiv({ cls: "referee-warning", text: `This claim combines two sources: also cite ${m.together_with.source?.title || m.together_with.source?.url}.` });
      if (m.label === "supports" && year(m.source) && new Date().getFullYear() - year(m.source) > OLD_SOURCE_YEARS) {
        card.createDiv({ cls: "referee-warning", text: `This source is from ${year(m.source)}. Check whether newer evidence agrees.` });
      }
      if (m.mixed) card.createDiv({ cls: "referee-warning", text: `Mixed evidence: ${m.mixed.title || m.mixed.url} points the other way.` });
      if (m.label === "supports") {
        const cite = inText(m.source);
        card.createEl("button", { text: `Copy ${cite}` }).onclick = () => {
          navigator.clipboard.writeText(cite);
          new Notice("Citation copied");
        };
      }
      if (m.source?.url) card.createEl("button", { text: "Open source" }).onclick = () => window.open(m.source.url);
    }
  }
}

module.exports = class RefereePlugin extends Plugin {

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.checks = new Map();  // sentence -> { pending } or the server's reply
    this.lastPing = 0;
    this.timer = null;

    this.registerView(VIEW, (leaf) => new RefereeView(leaf, this));
    this.addRibbonIcon("check-circle", "Open Referee", () => this.openView());
    this.addCommand({ id: "open", name: "Open panel", callback: () => this.openView() });
    this.addCommand({ id: "check", name: "Check this note now", callback: () => this.checkNote() });
    this.addSettingTab(new RefereeSettings(this.app, this));

    this.registerEvent(this.app.workspace.on("editor-change", () => {
      this.ping();
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.checkNote(), PAUSE_MS);
    }));
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.redraw()));
  }

  onunload() { clearTimeout(this.timer); }

  async api(path, body) {
    const response = await requestUrl({
      url: this.settings.server.replace(/\/$/, "") + path,
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json", "X-Referee": "1" },
      body: body ? JSON.stringify(body) : undefined,
    });
    return response.json;
  }

  // Tells the server someone is writing, at most once a minute.
  ping() {
    if (Date.now() - this.lastPing < PING_EVERY) return;
    this.lastPing = Date.now();
    this.api("/writing", {}).catch(() => {});
  }

  noteText() {
    return this.app.workspace.getActiveViewOfType(MarkdownView)?.editor.getValue() || "";
  }

  results() {
    const current = new Set(sentences(this.noteText()));
    return [...this.checks].filter(([s]) => current.has(s));
  }

  async checkNote() {
    for (const sentence of sentences(this.noteText())) {
      if (this.checks.has(sentence)) continue;
      this.checks.set(sentence, { pending: true });
      this.api("/check", { sentence, project: this.settings.project })
        .then((r) => this.checks.set(sentence, { match: r.match ? r : null, needs_source: !r.match && Boolean(r.needs_source), closest: r.closest || [] }))
        .catch(() => this.checks.delete(sentence))  // server not running: try again next time
        .finally(() => this.redraw());
    }
    this.redraw();
  }

  redraw() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW)) leaf.view.draw();
  }

  async openView() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false);
      await leaf.setViewState({ type: VIEW, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
    this.checkNote();
  }
};

class RefereeSettings extends PluginSettingTab {

  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    new Setting(containerEl).setName("Server").setDesc("Where the Referee server is running.")
      .addText((t) => t.setValue(this.plugin.settings.server).onChange(async (v) => {
        this.plugin.settings.server = v.trim() || DEFAULTS.server;
        await this.plugin.saveData(this.plugin.settings);
      }));
    new Setting(containerEl).setName("Project").setDesc("Only check against reading saved for this project. Leave empty for all.")
      .addText((t) => t.setValue(this.plugin.settings.project).onChange(async (v) => {
        this.plugin.settings.project = v.trim();
        this.plugin.checks.clear();
        await this.plugin.saveData(this.plugin.settings);
      }));
  }
}
