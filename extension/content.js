// Runs on every page. While research mode is on, sends the page to the backend,
// which keeps it only if it has real article text.

const SKIP = [
  /\/\/(www\.)?google\.[^/]+\/search/,
  /\/\/(www\.)?bing\.com\/search/,
  /\/\/scholar\.google\./,
  /\/\/(mail|outlook|calendar|docs|drive)\./,
  /\/\/([^/]+\.)?(notion\.so|office\.com|live\.com|sharepoint\.com|overleaf\.com)\//,
  /\/\/([^/]+\.)?(facebook|instagram|twitter|x|tiktok|reddit|youtube|linkedin)\.com\//,
  /\/\/localhost[:/]/,
  /\/\/([^/]+\.)?(paypal|stripe|monzo|revolut|starlingbank|barclays|hsbc|natwest|lloydsbank|santander|nationwide|halifax|chase|wellsfargo|bankofamerica)\.(com|co\.uk)\//,
  /\/\/[^/]*(bank|banking)[^/]*\//,
  /\/(login|signin|sign-in|checkout|payment|account)(\/|\?|$)/,
];

// Anything a person could type into, plus code and embedded pages, is removed before
// the page leaves the tab: only readable content is sent.
const PRIVATE = "input, textarea, select, button, script, noscript, style, iframe, object, embed, template, [contenteditable]";

function readableHtml() {
  const copy = document.documentElement.cloneNode(true);
  copy.querySelectorAll(PRIVATE).forEach((element) => element.remove());
  return copy.outerHTML;
}

(async () => {
  if (SKIP.some((pattern) => pattern.test(location.href))) return;
  const { research, mode } = await chrome.storage.local.get(["research", "mode"]);
  // In automatic mode, writing in Word (its Referee panel is open) also counts as researching.
  const writing = !research && (mode ?? "auto") === "auto" && (await chrome.runtime.sendMessage({ type: "writing" }));
  if (!research && !writing) return;
  if (document.querySelector('input[type="password"]')) return; // login, banking and account pages

  chrome.runtime.sendMessage(
    { type: "capture", body: { url: location.href, html: readableHtml() } },
    (result) => console.log("[Referee] capture:", result)
  );
})();
