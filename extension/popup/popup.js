const research = document.getElementById("research");
const duration = document.getElementById("duration");
const mode = document.getElementById("mode");
const statusLine = document.getElementById("status");
const savedList = document.getElementById("saved-list");
const savedTitle = document.getElementById("saved-title");
const savedEmpty = document.getElementById("saved-empty");
const server = document.getElementById("server");

const CAPTURE_STATUS = {
  saved: (c) => `Saved · ${c.passages} passages`,
  already: () => "Already saved",
  skipped: (c) => `Not saved: ${c.reason || "no article text found"}`,
  offline: () => "Not saved: the server wasn't running",
};

// The pages Referee has captured, most recent first.
async function showSaved() {
  const { captures = [] } = await chrome.storage.local.get("captures");
  savedList.replaceChildren(...captures.slice(0, 20).map((c) => {
    const item = document.createElement("li");
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = c.title;
    title.title = c.url;
    const status = document.createElement("span");
    status.className = "s";
    status.dataset.status = c.status;
    status.textContent = (CAPTURE_STATUS[c.status] || (() => c.status))(c);
    item.append(title, status);
    return item;
  }));
  const saved = captures.filter((c) => c.status === "saved").length;
  savedTitle.textContent = saved ? `Saved pages (${saved})` : "Saved pages";
  savedEmpty.hidden = captures.length > 0;
}

async function showServer() {
  const online = await chrome.runtime.sendMessage({ type: "server" });
  server.dataset.state = online ? "online" : "offline";
  server.textContent = online ? "Server running" : "Server not running";
}

async function showStatus() {
  const state = await chrome.storage.local.get(["research", "until", "duration", "mode"]);
  research.checked = Boolean(state.research);
  duration.value = state.duration ?? "60";
  mode.value = state.mode ?? "auto";
  const writing = !state.research && (state.mode ?? "auto") === "auto" &&
    (await chrome.runtime.sendMessage({ type: "writing" }));
  if (writing) {
    statusLine.textContent = "You're writing: capturing articles you read.";
    statusLine.className = "";
  } else if (!state.research) {
    statusLine.textContent = "Not reading anything.";
    statusLine.className = "off";
  } else if (state.until) {
    const minutes = Math.max(1, Math.round((state.until - Date.now()) / 60000));
    statusLine.textContent = `Capturing articles you read · off in ${minutes} min`;
    statusLine.className = "";
  } else {
    statusLine.textContent = "Capturing articles you read.";
    statusLine.className = "";
  }
}

research.addEventListener("change", async () => {
  await chrome.runtime.sendMessage({ type: "setResearch", on: research.checked, minutes: Number(duration.value) });
  showStatus();
});

duration.addEventListener("change", async () => {
  await chrome.storage.local.set({ duration: duration.value });
  if (research.checked) {
    await chrome.runtime.sendMessage({ type: "setResearch", on: true, minutes: Number(duration.value) });
  }
  showStatus();
});

const modeHint = document.getElementById("mode-hint");
function showModeHint() {
  modeHint.hidden = mode.value !== "auto";
}
mode.addEventListener("change", () => {
  chrome.storage.local.set({ mode: mode.value });
  showModeHint();
});

document.getElementById("open-editor").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("editor/editor.html") });
  window.close();
});

document.getElementById("forget").addEventListener("click", async () => {
  if (!confirm("Forget every saved page? Referee won't be able to cite them any more.")) return;
  await chrome.runtime.sendMessage({ type: "clear" });
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.captures) showSaved();
});

showStatus().then(showModeHint);
showSaved();
showServer();
