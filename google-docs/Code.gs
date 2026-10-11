// Referee for Google Docs. The sidebar (Sidebar.html) runs in your browser, so it can reach
// the Referee server on your computer; these functions run on Google's side and only read
// and mark the document. Docs has no background add-ons, so the sidebar must stay open.

const TAG_COLOURS = { supports: "#c8f0d4", warn: "#fde7b0", contradicts: "#f9c9c4", needs: "#fdebd0" };
const HEADINGS = ["References", "Reference list", "Works Cited"];

function onOpen() {
  DocumentApp.getUi().createAddonMenu().addItem("Open Referee", "showSidebar").addToUi();
}

function onInstall() {
  onOpen();
}

function showSidebar() {
  const html = HtmlService.createTemplateFromFile("Sidebar").evaluate().setTitle("Referee");
  DocumentApp.getUi().showSidebar(html);
}

// Lets Sidebar.html pull in Cite.html.
function include(name) {
  return HtmlService.createHtmlOutputFromFile(name).getContent();
}

// The writing, without the reference list at the end.
function documentText() {
  const paragraphs = DocumentApp.getActiveDocument().getBody().getParagraphs();
  const lines = [];
  for (const p of paragraphs) {
    const text = p.getText();
    if (HEADINGS.includes(text.trim())) break;
    lines.push(text);
  }
  return lines.join("\n");
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Colours a sentence and, for supported claims, adds the in-text citation before its final
// punctuation. Returns false if the sentence can't be found (e.g. it was edited meanwhile).
function markSentence(sentence, kind, citation) {
  const body = DocumentApp.getActiveDocument().getBody();
  const core = sentence.replace(/[.!?]+["”’)]*$/, "");
  const found = body.findText(escapeRegex(core.slice(-200)));
  if (!found) return false;
  const text = found.getElement().asText();
  const start = found.getStartOffset();
  const end = found.getEndOffsetInclusive();
  text.setBackgroundColor(start, end, TAG_COLOURS[kind] || null);
  if (citation && !text.getText().slice(end + 1, end + 1 + citation.length + 1).includes(citation)) {
    text.insertText(end + 1, " " + citation);
    text.setBackgroundColor(end + 1, end + 1 + citation.length, null);
  }
  return true;
}

// Removes Referee's colours from the whole document.
function clearMarks() {
  const body = DocumentApp.getActiveDocument().getBody();
  const text = body.editAsText();
  const length = text.getText().length;
  if (length) text.setBackgroundColor(0, length - 1, null);
}

// Adds any missing entries under a reference heading at the end, starting it on a new page.
function addReferences(heading, entries) {
  const body = DocumentApp.getActiveDocument().getBody();
  const existing = new Set(body.getParagraphs().map((p) => p.getText().trim()));
  const missing = entries.filter((e) => !existing.has(e.trim()));
  if (!missing.length) return 0;
  if (!HEADINGS.some((h) => existing.has(h))) {
    body.appendPageBreak();
    body.appendParagraph(heading).setHeading(DocumentApp.ParagraphHeading.HEADING1);
  }
  for (const entry of missing) {
    body.appendParagraph(entry).setHeading(DocumentApp.ParagraphHeading.NORMAL).setIndentFirstLine(0).setIndentStart(0);
  }
  return missing.length;
}

// Numbered styles keep each source's number for the life of the document.
function getNumbers() {
  return JSON.parse(PropertiesService.getDocumentProperties().getProperty("referee-numbers") || "{}");
}

function setNumbers(numbers) {
  PropertiesService.getDocumentProperties().setProperty("referee-numbers", JSON.stringify(numbers));
}

function getSettings() {
  const props = PropertiesService.getDocumentProperties();
  return { style: props.getProperty("referee-style") || "apa", project: props.getProperty("referee-project") || "" };
}

function saveSettings(settings) {
  PropertiesService.getDocumentProperties().setProperties({ "referee-style": settings.style, "referee-project": settings.project });
}
