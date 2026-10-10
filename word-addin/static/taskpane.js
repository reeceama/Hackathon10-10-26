// Word task pane: checks every sentence against the backend, then adds APA 7 in-text
// citations and a reference list for supported claims, and comments for contradictions,
// misquotes and close copying.

const PARALLEL = 4; // sentences checked at once
const TAG = "referee"; // marks the sentences Referee has highlighted, so they can be cleared
// Same scheme as the browser editor: green supported, yellow card for wording, red card for
// contradictions. Word only shows its own highlighter colours, so these are its palette names.
const HIGHLIGHT = { supports: "BrightGreen", warn: "Yellow", contradicts: "Red", misquote: "Yellow" };
// Word mutes highlights in dark mode but keeps coloured text readable, so dark mode colours
// the sentence (and with it the underline) instead. Each mark also has its own underline
// shape - like Word's spelling (wavy) and grammar marks - so it never relies on colour alone.
const TEXT_COLOUR = { supports: "#2E9E5B", warn: "#D99A00", contradicts: "#E5484D", misquote: "#D99A00" };
const UNDERLINE = { supports: "Single", warn: "Dotted", contradicts: "Wave", misquote: "Dotted" };
const COMMENT_PREFIX = "Referee: "; // marks Referee's own comments, so it can replace or clear them
const MIN_WORDS = 5; // the backend ignores shorter sentences anyway
const CHECKED = "referee-checked"; // document setting: sentences already checked, saved in the .docx
// One or more APA in-text citations at the end of a sentence, e.g. " (Smith, 2023)".
const ADDED_CITATION = /(?:\s*\([^()]*,\s*(?:\d{4}|n\.d\.|no date)\)|\s*\[\d+\])+(?=[.!?]["”’)]*$)/;
const STYLE_SETTING = "referee-style"; // document setting: "apa", "harvard" or "ieee"
const NUMBERS_SETTING = "referee-numbers"; // document setting: source URL -> IEEE number, in order of first citation
const PROJECT_SETTING = "referee-project"; // document setting: only check against this project's reading
const AUTO_SETTING = "referee-auto"; // document setting: check as the person writes
const PAUSE_MS = 2500; // automatic checks wait for a pause in writing
const LIST_HEADINGS = ["References", "Reference list"];

const button = document.getElementById("check");
const selectionButton = document.getElementById("check-selection");
const recheckButton = document.getElementById("recheck");
const clearButton = document.getElementById("clear");
const darkToggle = document.getElementById("dark");
const styleSelect = document.getElementById("style");
const autoToggle = document.getElementById("auto");
const projectInput = document.getElementById("project");
const statusBox = document.getElementById("status");
const resultsList = document.getElementById("results");

Office.onReady(() => {
  button.onclick = () => runCheck("document", false);
  selectionButton.onclick = () => runCheck("selection", true);
  recheckButton.onclick = () => runCheck("document", true);
  clearButton.onclick = clearHighlights;
  darkToggle.checked = officeIsDark();
  styleSelect.value = Office.context.document.settings.get(STYLE_SETTING) || "apa";
  styleSelect.onchange = async () => {
    Office.context.document.settings.set(STYLE_SETTING, styleSelect.value);
    Office.context.document.settings.saveAsync();
    setStatus(`${currentStyle().name} will be used for citations in this document.`);
    // Word-managed citations and bibliography reformat themselves in the new style.
    if (useWordTools) {
      await Word.run(async (context) => {
        await addWordSources(context, []);
        await updateWordFields(context);
      }).catch(() => {});
    }
  };
  projectInput.value = Office.context.document.settings.get(PROJECT_SETTING) || "";
  projectInput.onchange = () => {
    Office.context.document.settings.set(PROJECT_SETTING, projectInput.value.trim());
    Office.context.document.settings.saveAsync();
  };
  setBusy(false);

  // Check as the person writes: Word reports cursor/selection changes while typing, and a
  // check runs once they pause. Only finished, unchecked sentences are sent.
  const settings = Office.context.document.settings;
  autoToggle.checked = settings.get(AUTO_SETTING) ?? true;
  autoToggle.onchange = () => {
    settings.set(AUTO_SETTING, autoToggle.checked);
    settings.saveAsync();
    showWatching();
    if (autoToggle.checked) scheduleAutoCheck();
  };
  Office.context.document.addHandlerAsync(Office.EventType.DocumentSelectionChanged, scheduleAutoCheck);

  // Keep running in the background after the panel is closed, and start with the document
  // without opening the panel. Needs Word's shared runtime; older Word versions ignore this
  // and Referee runs while its panel is open instead.
  try {
    Office.addin.setStartupBehavior(Office.StartupBehavior.load);
  } catch (error) {
    console.info("Background mode not available in this version of Word:", error);
  }

  // Reopen this panel whenever the document is opened, so Referee keeps working unprompted.
  settings.set("Office.AutoShowTaskpaneWithDocument", true);
  settings.saveAsync();


  showWatching();
  if (autoToggle.checked) scheduleAutoCheck();
});

let pauseTimer;
let running = false;
let pending = false;

function showWatching() {
  setStatus(autoToggle.checked
    ? "Watching as you write: each sentence is checked when you finish it."
    : "Automatic checking is off. Use the buttons above to check.");
}

// Tell the backend someone is writing (at most once a minute), so the browser extension in
// automatic mode captures what they read only while they're writing in Word.
let lastSignal = 0;
function signalWriting() {
  if (Date.now() - lastSignal < 60 * 1000) return;
  lastSignal = Date.now();
  fetch("/api/writing", { method: "POST" }).catch(() => {});
}

function scheduleAutoCheck() {
  signalWriting();
  if (!autoToggle.checked) return;
  clearTimeout(pauseTimer);
  pauseTimer = setTimeout(() => runCheck("document", false, true), PAUSE_MS);
}

// One check at a time; a request that arrives mid-check runs straight after it.
async function runCheck(scope, force, automatic = false) {
  if (running) {
    pending = true;
    return;
  }
  running = true;
  try {
    await check(scope, force, automatic);
  } finally {
    running = false;
    if (pending) {
      pending = false;
      scheduleAutoCheck();
    }
  }
}

// True when Office is using a dark theme (Word then shows documents on a dark page).
function officeIsDark() {
  try {
    const background = Office.context.officeTheme?.bodyBackgroundColor;
    if (!background) return window.matchMedia("(prefers-color-scheme: dark)").matches;
    const n = parseInt(background.replace("#", ""), 16);
    const brightness = 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
    return brightness < 128;
  } catch {
    return false;
  }
}

function setBusy(busy) {
  for (const b of [button, selectionButton, recheckButton, clearButton]) b.disabled = busy;
}

// The sentence as first written, so adding a citation doesn't make it look new. Linked
// citations can come back from Word with hidden link codes, so those are removed too, along
// with any author-date brackets.
function sentenceKey(sentence) {
  return sentence
    .replace(/HYPERLINK\s+(\\l\s+)?"[^"]*"/g, "")
    .replace(/\s*\([^()]*,\s*(?:\d{4}|n\.d\.|no date)\)/g, "")
    .replace(/\s+([.!?])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function checkedSentences() {
  return new Set(Office.context.document.settings.get(CHECKED) || []);
}

function saveCheckedSentences(sentences) {
  Office.context.document.settings.set(CHECKED, [...sentences]);
  return new Promise((resolve) => Office.context.document.settings.saveAsync(resolve));
}

const RESULT_LABELS = { supports: "Supported", contradicts: "Contradicted", misquote: "Misquote" };

// Shorten at a word boundary rather than mid-word.
function shorten(text, limit) {
  if (text.length <= limit) return text;
  return text.slice(0, text.lastIndexOf(" ", limit)).replace(/[,;:]$/, "") + "…";
}

function setStatus(text) {
  statusBox.textContent = text;
}

function addResult(text) {
  const item = document.createElement("li");
  item.textContent = text;
  resultsList.appendChild(item);
}

// Finished sentences only, so the sentence still being typed is left alone. A selection
// may end mid-sentence, so selected text can include an unfinished one.
function splitSentences(text, includeUnfinished = false) {
  const pattern = includeUnfinished ? /[^.!?]+[.!?]+["”’)]*|[^.!?]+$/g : /[^.!?]+[.!?]+["”’)]*/g;
  return (text.match(pattern) || [])
    .map((s) => s.trim())
    .filter((s) => s.split(/\s+/).length >= MIN_WORDS);
}

async function post(path, body) {
  const response = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

// Run fn over items with at most `limit` running at once, keeping results in order.
async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i]).catch(() => null);
    }
  }
  await Promise.all(Array.from({ length: limit }, worker));
  return results;
}

// --- Referencing styles for web pages: APA 7 and Harvard (Cite Them Right) ---

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const ORGANISATION = /\b(foundation|university|college|ltd|inc|plc|council|society|association|institute|organi[sz]ation|bbc|nhs|news|press|journal|times|guardian|agency|department|government|ministry|wikipedia|trust|group|centre|center|service|office|unit)\b/i;
const MINOR_WORDS = /^(a|an|and|as|at|but|by|for|in|nor|of|on|or|so|the|to|up|yet)$/i;

function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function cleanSite(site) {
  return (site || "").replace(/,?\s*(Inc|Ltd|LLC|plc)\.?$/i, "").trim();
}

// "Mediterranean diet - Wikipedia" -> "Mediterranean diet"
function cleanTitle(title) {
  return (title || "Untitled").replace(/\s+[-|–—]\s+[^-|–—]+$/, "").trim();
}

function titleCase(text) {
  return text.split(" ").map((word, i) =>
    i > 0 && MINOR_WORDS.test(word) ? word.toLowerCase() : word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function isWikipedia(source) {
  return /(^|\.)wikipedia\.org$/.test(hostname(source.url));
}

// Page metadata often has no usable author; both styles then use the organisation.
function author(source) {
  const name = (source.author || "").trim();
  const usable = name && name.split(/\s+/).length <= 6 && !/databases|authority control/i.test(name);
  return usable ? name : cleanSite(source.site) || hostname(source.url) || cleanTitle(source.title);
}

function isPerson(name) {
  const words = name.split(/\s+/);
  return words.length >= 2 && words.length <= 4 && !ORGANISATION.test(name) &&
    words.every((word) => /^[A-Z][a-z'’-]+\.?$/.test(word));
}

// "Jane Anne Smith" -> APA "Smith, J. A." / Harvard "Smith, J.A."
function listName(name, separator) {
  if (!isPerson(name)) return name;
  const words = name.split(/\s+/);
  const surname = words.pop();
  return `${surname}, ${words.map((word) => word[0] + ".").join(separator)}`;
}

function citationName(name) {
  return isPerson(name) ? name.split(/\s+/).pop() : name;
}

function parts(iso) {
  const [year, month, day] = String(iso || "").split("-");
  return { year, month: month ? MONTHS[Number(month) - 1] : "", day: day ? Number(day) : "" };
}

function accessed(source) {
  return source.captured_at || new Date().toISOString().slice(0, 10);
}

function endStop(text) {
  return /[?!.]$/.test(text) ? text : `${text}.`;
}

const STYLES = {
  apa: {
    name: "APA 7",
    heading: "References",
    headingAlignment: "Centered",
    hangingIndent: true,
    inText(source) {
      if (isWikipedia(source)) return `("${titleCase(cleanTitle(source.title))}," n.d.)`;
      return `(${citationName(author(source))}, ${parts(source.date).year || "n.d."})`;
    },
    // Webpages: Author. (Year, Month Day). Title. Site. URL
    // Wikipedia (changes over time, so it has a retrieval date):
    //   Title. (n.d.). In Wikipedia. Retrieved Month Day, Year, from URL
    reference(source) {
      const title = cleanTitle(source.title);
      if (isWikipedia(source)) {
        const a = parts(accessed(source));
        return { text: `${title}. (n.d.). In Wikipedia. Retrieved ${a.month} ${a.day}, ${a.year}, from ${source.url}`, italic: "Wikipedia" };
      }
      const name = listName(author(source), " ").replace(/\.$/, "");
      const d = parts(source.date);
      const date = d.year ? [d.year, [d.month, d.day].filter(Boolean).join(" ")].filter(Boolean).join(", ") : "n.d.";
      const site = cleanSite(source.site);
      const sitePart = site && site !== author(source) ? ` ${site}.` : "";
      return { text: `${name}. (${date}). ${endStop(title)}${sitePart} ${source.url || ""}`.trim(), italic: title };
    },
  },
  harvard: {
    name: "Harvard",
    heading: "Reference list",
    headingAlignment: "Left",
    hangingIndent: false,
    inText(source) {
      if (isWikipedia(source)) return `('${cleanTitle(source.title)}', ${parts(accessed(source)).year})`;
      return `(${citationName(author(source))}, ${parts(source.date).year || "no date"})`;
    },
    // Webpages: Author (Year) Title. Available at: URL (Accessed: Day Month Year).
    // Wikipedia: 'Title' (Year) Wikipedia. Available at: URL (Accessed: Day Month Year).
    reference(source) {
      const title = cleanTitle(source.title);
      const a = parts(accessed(source));
      const tail = `Available at: ${source.url} (Accessed: ${a.day} ${a.month} ${a.year}).`;
      if (isWikipedia(source)) return { text: `'${title}' (${a.year}) Wikipedia. ${tail}`, italic: "Wikipedia" };
      const name = listName(author(source), "");
      const year = parts(source.date).year || "no date";
      return { text: `${name} (${year}) ${endStop(title)} ${tail}`, italic: title };
    },
  },
};

// IEEE numbers sources in the order they are first cited, and keeps the number for the
// rest of the document.
function sourceNumber(source) {
  const settings = Office.context.document.settings;
  const numbers = settings.get(NUMBERS_SETTING) || {};
  const key = source.url || source.title || "";
  if (!numbers[key]) {
    numbers[key] = Object.keys(numbers).length + 1;
    settings.set(NUMBERS_SETTING, numbers);
    settings.saveAsync();
  }
  return numbers[key];
}

STYLES.ieee = {
  name: "IEEE",
  heading: "References",
  headingAlignment: "Left",
  hangingIndent: false,
  numbered: true,
  inText(source) {
    return `[${sourceNumber(source)}]`;
  },
  // Webpages: [n] A. Author, "Title," Site. Accessed: Mon. Day, Year. [Online]. Available: URL
  reference(source) {
    const name = author(source);
    const who = isPerson(name) ? name.split(/\s+/).map((w, i, all) => i < all.length - 1 ? `${w[0]}.` : w).join(" ") : name;
    const a = parts(accessed(source));
    const site = cleanSite(source.site) || hostname(source.url);
    const month = a.month ? `${a.month.slice(0, 3)}${a.month.length > 4 ? "." : ""} ` : "";
    return {
      text: `[${sourceNumber(source)}] ${who}, "${cleanTitle(source.title)}," ${site}. Accessed: ${month}${a.day}, ${a.year}. [Online]. Available: ${source.url}`,
      italic: site,
    };
  },
};

// A stable, hidden bookmark name for a reference entry, so citations can link to it.
// Word bookmark names: start with a letter (or _ for hidden), letters/digits/_ only, max 40 chars.
function bookmarkName(referenceText) {
  let hash = 0;
  for (const char of referenceText) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `_Referee_${hash.toString(36)}`;
}

// --- Word's own References tool: sources in the Source Manager, CITATION fields and a
// BIBLIOGRAPHY field, which Word formats in the style chosen under References > Style.
// There is no official add-in API for this, so Referee writes the same document parts
// Word uses; if Word rejects them, it falls back to plain-text citations. ---

const BIBLIOGRAPHY_NS = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography";
const WORD_STYLES = {
  apa: { file: "\\APASixthEditionOfficeOnline.xsl", name: "APA" },
  harvard: { file: "\\HarvardAnglia2008OfficeOnline.xsl", name: "Harvard - Anglia" },
  ieee: { file: "\\IEEE2006OfficeOnline.xsl", name: "IEEE" },
};
const BIBLIOGRAPHY_SETTING = "referee-word-bibliography"; // document setting: Word bibliography inserted
let useWordTools = true; // switched off for this session if Word rejects its citation parts

function xml(text) {
  return String(text ?? "").replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[c]);
}

// Word citation tags: short, letters and digits only, stable for the same source.
function sourceTag(source) {
  let hash = 0;
  for (const char of source.url || source.title || "") hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `Ref${hash.toString(36)}`;
}

function sourceXml(source) {
  const name = author(source);
  const published = parts(source.date);
  const read = parts(accessed(source));
  // Each person goes in Word's Author field ("Copeland, B.J."; several split on ";", "and" or "&").
  // Anything that isn't a person's name goes in Corporate Author.
  const people = name.split(/;|\s+and\s+|\s*&\s*/).map((n) => n.trim()).filter(Boolean).map((n) => {
    const comma = /^([^,]+),\s*(.+)$/.exec(n);
    if (comma) return { last: comma[1], first: comma[2] };
    if (!isPerson(n)) return null;
    const words = n.split(/\s+/);
    return { last: words.pop(), first: words.join(" ") };
  });
  let who = `<b:Corporate>${xml(name)}</b:Corporate>`;
  if (people.length && people.every(Boolean)) {
    who = `<b:NameList>${people.map((n) =>
      `<b:Person><b:Last>${xml(n.last)}</b:Last><b:First>${xml(n.first)}</b:First></b:Person>`).join("")}</b:NameList>`;
  }
  return `<b:Source><b:Tag>${sourceTag(source)}</b:Tag><b:SourceType>InternetSite</b:SourceType>` +
    `<b:Guid>{${crypto.randomUUID().toUpperCase()}}</b:Guid><b:Title>${xml(cleanTitle(source.title))}</b:Title>` +
    (published.year ? `<b:Year>${published.year}</b:Year>` : "") +
    (published.month ? `<b:Month>${published.month}</b:Month>` : "") +
    (published.day ? `<b:Day>${published.day}</b:Day>` : "") +
    `<b:Author><b:Author>${who}</b:Author></b:Author>` +
    `<b:InternetSiteTitle>${xml(cleanSite(source.site) || hostname(source.url))}</b:InternetSiteTitle>` +
    `<b:URL>${xml(source.url)}</b:URL><b:YearAccessed>${read.year}</b:YearAccessed>` +
    `<b:MonthAccessed>${read.month}</b:MonthAccessed><b:DayAccessed>${read.day}</b:DayAccessed></b:Source>`;
}

// Adds sources to the document's source list (what Word's Source Manager shows), and sets
// the list's style to the one chosen in the panel.
async function addWordSources(context, sources) {
  const lists = context.document.customXmlParts.getByNamespace(BIBLIOGRAPHY_NS);
  lists.load("items");
  await context.sync();
  let existing = null;
  if (lists.items.length) {
    const result = lists.items[0].getXml();
    await context.sync();
    existing = result.value;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(
    existing || `<b:Sources xmlns:b="${BIBLIOGRAPHY_NS}" xmlns="${BIBLIOGRAPHY_NS}"></b:Sources>`, "application/xml");
  const root = doc.documentElement;
  const style = WORD_STYLES[styleSelect.value] || WORD_STYLES.apa;
  root.setAttribute("SelectedStyle", style.file);
  root.setAttribute("StyleName", style.name);
  const tags = new Set([...doc.getElementsByTagNameNS(BIBLIOGRAPHY_NS, "Tag")].map((tag) => tag.textContent));
  for (const source of sources) {
    if (tags.has(sourceTag(source))) continue;
    const fragment = parser.parseFromString(`<b:Sources xmlns:b="${BIBLIOGRAPHY_NS}">${sourceXml(source)}</b:Sources>`, "application/xml");
    root.appendChild(doc.importNode(fragment.documentElement.firstElementChild, true));
    tags.add(sourceTag(source));
  }
  for (const list of lists.items) list.delete();
  context.document.customXmlParts.add(new XMLSerializer().serializeToString(doc));
  await context.sync();
}

function ooxmlPackage(bodyXml) {
  return `<pkg:package xmlns:pkg="http://schemas.microsoft.com/office/2006/xmlPackage">` +
    `<pkg:part pkg:name="/_rels/.rels" pkg:contentType="application/vnd.openxmlformats-package.relationships+xml"><pkg:xmlData>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>` +
    `</Relationships></pkg:xmlData></pkg:part>` +
    `<pkg:part pkg:name="/word/document.xml" pkg:contentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"><pkg:xmlData>` +
    `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${bodyXml}</w:body></w:document>` +
    `</pkg:xmlData></pkg:part></pkg:package>`;
}

function sdtId() {
  return Math.floor(Math.random() * 2000000000);
}

// A Word citation field, showing `display` until Word reformats it.
function citationOoxml(source, display) {
  return ooxmlPackage(`<w:p><w:r><w:t xml:space="preserve"> </w:t></w:r>` +
    `<w:sdt><w:sdtPr><w:id w:val="${sdtId()}"/><w:citation/></w:sdtPr><w:sdtContent>` +
    `<w:r><w:fldChar w:fldCharType="begin"/></w:r>` +
    `<w:r><w:instrText xml:space="preserve"> CITATION ${sourceTag(source)} \\l 2057 </w:instrText></w:r>` +
    `<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>${xml(display)}</w:t></w:r>` +
    `<w:r><w:fldChar w:fldCharType="end"/></w:r></w:sdtContent></w:sdt></w:p>`);
}

// Word's bibliography block: a heading and a BIBLIOGRAPHY field, pre-filled with Referee's
// entries until Word updates it.
function bibliographyOoxml(heading, entries) {
  const cached = entries.map((text) =>
    `<w:p><w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr><w:r><w:t xml:space="preserve">${xml(text)}</w:t></w:r></w:p>`).join("");
  return ooxmlPackage(`<w:sdt><w:sdtPr><w:id w:val="${sdtId()}"/><w:docPartObj><w:docPartGallery w:val="Bibliographies"/><w:docPartUnique/></w:docPartObj></w:sdtPr><w:sdtContent>` +
    `<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>${xml(heading)}</w:t></w:r></w:p>` +
    `<w:sdt><w:sdtPr><w:id w:val="${sdtId()}"/><w:bibliography/></w:sdtPr><w:sdtContent>` +
    `<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> BIBLIOGRAPHY </w:instrText></w:r>` +
    `<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>${cached}` +
    `<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:sdtContent></w:sdt></w:sdtContent></w:sdt>`);
}

// Asks Word to refresh its citation and bibliography fields, where Word supports it.
async function updateWordFields(context) {
  try {
    const fields = context.document.body.fields;
    fields.load("items");
    await context.sync();
    for (const field of fields.items) field.updateResult();
    await context.sync();
  } catch (error) {
    console.warn("Referee couldn't refresh Word's fields:", error);
  }
}

// Adds new sources and, the first time, Word's bibliography on a new page at the end.
// Returns how many new sources were added.
async function addWordBibliography(context, body, paragraphs, sources, references) {
  const settings = Office.context.document.settings;
  const before = (settings.get("referee-word-sources") || []);
  const fresh = sources.filter((source) => !before.includes(sourceTag(source)));
  await addWordSources(context, sources);
  settings.set("referee-word-sources", [...new Set([...before, ...sources.map(sourceTag)])]);

  const hasList = settings.get(BIBLIOGRAPHY_SETTING) ||
    paragraphs.items.some((p) => LIST_HEADINGS.includes((p.text || "").trim()));
  if (!hasList && sources.length) {
    body.insertBreak("Page", "End");
    const entries = [...references.keys()].sort((a, b) => a.localeCompare(b));
    body.getRange("End").insertOoxml(bibliographyOoxml(currentStyle().heading, entries), "End");
    await context.sync();
    settings.set(BIBLIOGRAPHY_SETTING, true);
  }
  settings.saveAsync();
  await updateWordFields(context);
  return fresh.length;
}

function currentStyle() {
  return STYLES[styleSelect.value] || STYLES.apa;
}

function comments(match) {
  const notes = [];
  if (match.label === "contradicts") {
    notes.push(`⚠ Your source says otherwise: "${match.quote}" (${match.source?.title || "source"})`);
  }
  if (match.misquote) {
    notes.push(`This quotation doesn't match the source exactly. The source says: "${match.quote}"`);
  }
  if (match.too_close) {
    notes.push("Very close to the source's wording. Consider quoting it or rephrasing.");
  }
  return notes.map((note) => COMMENT_PREFIX + note);
}

function isRefereeComment(comment) {
  return (comment.content || "").startsWith(COMMENT_PREFIX) || /^⚠ Your source says otherwise|^This quotation doesn't match|^Very close to the source's wording/.test(comment.content || "");
}

// scope: "document" (every paragraph before the reference list) or "selection".
// force: check sentences again even if they were checked before.
// automatic: a background check while writing - quiet when there's nothing new.
async function check(scope, force, automatic = false) {
  setBusy(true);
  if (!automatic) resultsList.innerHTML = "";
  try {
    await Word.run(async (context) => {
      const body = context.document.body;
      const paragraphs = body.paragraphs;
      paragraphs.load("items/text");
      body.load("text");
      const selection = context.document.getSelection();
      selection.load("text");
      await context.sync();

      // Each sentence remembers where to search for it.
      let sentences = [];
      if (scope === "selection") {
        for (const sentence of splitSentences(selection.text || "", true)) sentences.push({ paragraph: selection, sentence });
        if (sentences.length === 0) {
          setStatus(`Select one or more full sentences (${MIN_WORDS}+ words, ending in a full stop) first.`);
          return;
        }
      } else {
        for (const paragraph of paragraphs.items) {
          if (LIST_HEADINGS.includes((paragraph.text || "").trim())) break; // never check the reference list
          for (const sentence of splitSentences(paragraph.text || "")) sentences.push({ paragraph, sentence });
        }
        // Some Word versions report paragraph text unreliably, so fall back to the whole body.
        if (sentences.length === 0) {
          const text = (body.text || "").split(/\n\s*(?:References|Reference list)\s*\n/)[0];
          for (const sentence of splitSentences(text)) sentences.push({ paragraph: body, sentence });
        }
      }

      // Number repeated copies of a sentence within the same paragraph (0 = first copy).
      const copies = new Map();
      for (const item of sentences) {
        const key = sentenceKey(item.sentence);
        const counts = copies.get(item.paragraph) || new Map();
        item.occurrence = counts.get(key) || 0;
        counts.set(key, item.occurrence + 1);
        copies.set(item.paragraph, counts);
      }

      const checked = checkedSentences();
      const total = sentences.length;
      if (!force) sentences = sentences.filter(({ sentence }) => !checked.has(sentenceKey(sentence)));
      if (sentences.length === 0) {
        if (automatic) return showWatching();
        setStatus(total
          ? `Nothing new to check: all ${total} sentences were checked before. Use "Re-check everything" after reading new sources.`
          : `No sentences long enough to check. Sentences need ${MIN_WORDS}+ words and a full stop.`);
        return;
      }

      let done = 0;
      setStatus(`Checking ${sentences.length} new sentence${sentences.length === 1 ? "" : "s"}…`);
      const matches = await mapLimit(sentences, PARALLEL, async ({ sentence }) => {
        const result = await post("check", { sentence: sentenceKey(sentence), project: projectInput.value.trim() });
        if (!automatic) setStatus(`Checking ${++done} of ${sentences.length} sentences…`);
        return result;
      });

      let citations = 0;
      let warnings = 0;
      let failed = 0;
      const references = new Map(); // reference text -> title (to italicise)
      const sources = new Map(); // source tag -> source, for Word's source list
      for (let i = 0; i < sentences.length; i++) {
        const match = matches[i];
        if (!match) continue; // request failed: leave it unchecked so it's tried again next time
        checked.add(sentenceKey(sentences[i].sentence));
        if (!match.match) continue;

        try {
          // The citation goes before the sentence's closing punctuation, so search for the
          // sentence without it (Word's search is limited to 255 characters).
          const { paragraph, sentence } = sentences[i];
          const core = sentenceKey(sentence).replace(/[.!?]+["”’)]*$/, "");
          const found = paragraph.search(core.slice(-250), { matchCase: true });
          found.load("items");
          await context.sync();
          // The same sentence can appear more than once in a paragraph: use the right copy.
          const { occurrence } = sentences[i];
          if (found.items.length <= occurrence) continue;
          const range = found.items[occurrence];

          // Reuse the sentence's highlight from an earlier check, or wrap it in a hidden,
          // tagged content control so the colour can be removed later. Referee's own earlier
          // comments on it are removed, so checking again replaces rather than duplicates.
          const parent = range.parentContentControlOrNullObject;
          parent.load("tag,title");
          range.font.load("color");
          const oldComments = range.getComments();
          oldComments.load("items/content");
          await context.sync();
          for (const comment of oldComments.items) if (isRefereeComment(comment)) comment.delete();
          const alreadyMarked = !parent.isNullObject && parent.tag === TAG;
          let originalColour = range.font.color || "";
          if (!parent.isNullObject && parent.tag === TAG) {
            originalColour = (parent.title || "").split("|")[1] || originalColour;
          } else {
            // The title remembers the sentence's original text colour, so clearing can restore it.
            const control = range.insertContentControl();
            control.tag = TAG;
            control.title = `Referee|${originalColour}`;
            control.appearance = "Hidden";
          }
          const warned = match.label === "supports" && (match.misquote || match.too_close);
          const mark = warned ? "warn" : match.label;
          range.font.underline = UNDERLINE[mark];
          if (darkToggle.checked) {
            range.font.highlightColor = null;
            range.font.color = TEXT_COLOUR[mark];
          } else {
            if (originalColour) range.font.color = originalColour; // undo any dark-mode colouring
            range.font.highlightColor = HIGHLIGHT[mark];
          }

          if (match.label === "supports") {
            const citation = currentStyle().inText(match.source || {});
            const ref = currentStyle().reference(match.source || {});
            references.set(ref.text, ref.italic);
            sources.set(sourceTag(match.source || {}), match.source || {});
            if (!alreadyMarked && !sentence.includes(citation)) { // never cite the same sentence twice
              let inserted = false;
              if (useWordTools) {
                try {
                  range.insertOoxml(citationOoxml(match.source || {}, citation), "End");
                  await context.sync();
                  inserted = true;
                } catch (error) {
                  useWordTools = false; // fall back to plain-text citations from now on
                  console.warn("Word rejected a citation field; using plain text:", error);
                }
              }
              if (!inserted) {
                // Plain-text citation linked to its reference entry (Cmd/Ctrl+click to jump).
                const cite = range.insertText(" ", "End").insertText(citation, "After");
                cite.hyperlink = `#${bookmarkName(ref.text)}`;
              }
              citations++;
            }
          }
          for (const note of comments(match)) {
            range.insertComment(note);
            warnings++;
          }
          addResult(`${RESULT_LABELS[match.label] || match.label}: “${shorten(match.quote || "", 90)}”`);
          await context.sync(); // apply this sentence's changes now, so one failure can't undo the rest
        } catch (error) {
          failed++;
          checked.delete(sentenceKey(sentences[i].sentence)); // try it again next time
          console.error("Referee couldn't mark a sentence:", error);
        }
      }
      await context.sync();
      await saveCheckedSentences(checked);

      let added = 0;
      if (useWordTools && sources.size) {
        try {
          added = await addWordBibliography(context, body, paragraphs, [...sources.values()], references);
        } catch (error) {
          useWordTools = false;
          console.warn("Word rejected its bibliography parts; using a plain reference list:", error);
        }
      }
      if (!useWordTools) added = await addReferenceList(context, body, paragraphs, references);
      setStatus(
        `Checked ${sentences.length} sentence${sentences.length === 1 ? "" : "s"}: ` +
          `${citations} ${currentStyle().name} citation${citations === 1 ? "" : "s"}, ` +
          `${added} new reference${added === 1 ? "" : "s"}, ${warnings} comment${warnings === 1 ? "" : "s"}.` +
          (failed ? ` ${failed} sentence${failed === 1 ? "" : "s"} couldn't be marked.` : "")
      );
    });
  } catch (error) {
    setStatus(`Something went wrong: ${error.message}${error.debugInfo?.errorLocation ? ` (at ${error.debugInfo.errorLocation})` : ""}`);
  } finally {
    setBusy(false);
  }
}

// Appends the reference list on a new page at the end of the document, laid out for the
// selected style (APA: centred bold heading, hanging indent; Harvard: left-aligned heading),
// alphabetical, with italic titles. Entries already in the document are skipped.
// Returns how many were added.
async function addReferenceList(context, body, paragraphs, references) {
  const style = currentStyle();
  const existing = new Set(paragraphs.items.map((p) => (p.text || "").trim()));
  const entries = [...references].filter(([text]) => !existing.has(text)).sort(([a], [b]) => style.numbered ? parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10) : a.localeCompare(b));
  if (entries.length === 0) return 0;

  if (!LIST_HEADINGS.some((heading) => existing.has(heading))) {
    body.insertBreak("Page", "End"); // the reference list starts on a new page
    const heading = body.insertParagraph(style.heading, "End");
    heading.styleBuiltIn = "Normal";
    heading.alignment = style.headingAlignment;
    heading.font.bold = true;
  }
  const italics = [];
  for (const [text, italic] of entries) {
    const paragraph = body.insertParagraph(text, "End");
    paragraph.styleBuiltIn = "Normal";
    paragraph.alignment = "Left";
    paragraph.font.bold = false;
    paragraph.leftIndent = style.hangingIndent ? 36 : 0;
    paragraph.firstLineIndent = style.hangingIndent ? -36 : 0;
    const found = paragraph.search(italic, { matchCase: true });
    found.load("items");
    italics.push(found);
  }
  await context.sync();
  for (const found of italics) {
    if (found.items.length) found.items[0].font.italic = true;
  }
  await context.sync();

  // Bookmark each new entry so in-text citations can link to it. Kept separate so an older
  // version of Word without bookmark support still gets the reference list.
  try {
    for (const [text] of entries) {
      const found = body.search(text.slice(0, 250), { matchCase: true });
      found.load("items");
      await context.sync();
      if (found.items.length) found.items[found.items.length - 1].insertBookmark(bookmarkName(text));
    }
    await context.sync();
  } catch (error) {
    console.warn("Referee couldn't add reference bookmarks:", error);
  }
  return entries.length;
}

// Removes everything Referee marked up - highlights and its own comments - keeping the
// text, citations and reference list, and anyone else's comments.
async function clearHighlights() {
  setBusy(true);
  try {
    await Word.run(async (context) => {
      const body = context.document.body;
      const controls = body.contentControls.getByTag(TAG);
      controls.load("items/title");
      const allComments = body.getComments();
      allComments.load("items/content");
      await context.sync();
      for (const control of controls.items) {
        const content = control.getRange("Content");
        content.font.highlightColor = null;
        content.font.underline = "None";
        const originalColour = (control.title || "").split("|")[1];
        if (originalColour) content.font.color = originalColour;
        control.delete(true); // true keeps the content
      }
      const ours = allComments.items.filter(isRefereeComment);
      for (const comment of ours) comment.delete();
      await context.sync();
      setStatus(`Cleared ${controls.items.length} highlight${controls.items.length === 1 ? "" : "s"} ` +
        `and ${ours.length} comment${ours.length === 1 ? "" : "s"}.`);
    });
  } catch (error) {
    setStatus(`Couldn't clear Referee's marks: ${error.message}`);
  } finally {
    setBusy(false);
  }
}
