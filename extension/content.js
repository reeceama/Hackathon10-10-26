// Runs on every page. While research mode is on, it waits until the page has actually
// been read (open and visible for READ_MS, or text highlighted), then sends it to the
// backend, which keeps it only if it has real article text.

const READ_MS = 20000;      // time a page must be open and visible before it counts as read
const MIN_SELECTION = 20;   // highlighting this many characters also counts as reading

// Anything a person could type into, plus code and embedded pages, is removed before
// the page leaves the tab: only readable content is sent.
const PRIVATE = "input, textarea, select, button, script, noscript, style, iframe, object, embed, template, [contenteditable]";

function readableHtml() {
  const copy = document.documentElement.cloneNode(true);
  copy.querySelectorAll(PRIVATE).forEach((element) => element.remove());
  return copy.outerHTML;
}

// Research mode on, or (automatic mode only) the Word add-in reports someone writing.
async function capturing() {
  const { research, mode } = await chrome.storage.local.get(["research", "mode"]);
  if (research) return true;
  if ((mode ?? "auto") !== "auto") return false; // automatic is the default
  return Boolean(await chrome.runtime.sendMessage({ type: "writing" }));
}

if (!isSkipped(location.href)) {
  let sent = false;
  let visibleMs = 0;
  let last = Date.now();
  let nextTry = 0; // when research mode is off, re-check every 10s rather than every tick

  async function capture() {
    if (sent || Date.now() < nextTry) return;
    nextTry = Date.now() + 10000;
    if (document.querySelector('input[type="password"]')) return; // login, banking and account pages
    if (!(await capturing())) return;
    sent = true;
    clearInterval(timer);
    chrome.runtime.sendMessage(
      { type: "capture", body: { url: location.href, title: document.title, html: readableHtml() } },
      (result) => console.log("[Referee] capture:", result)
    );
  }

  // Count only time the tab is actually visible. Checked once a second; the storage
  // lookup in capturing() happens only when the page qualifies, not every tick.
  const timer = setInterval(() => {
    const now = Date.now();
    if (document.visibilityState === "visible") visibleMs += now - last;
    last = now;
    if (visibleMs >= READ_MS) capture().catch(() => {});
  }, 1000);

  document.addEventListener("mouseup", () => {
    if (String(window.getSelection()).trim().length >= MIN_SELECTION) capture().catch(() => {});
  });
}
