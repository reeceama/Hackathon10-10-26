const research = document.getElementById("research");
const duration = document.getElementById("duration");
const mode = document.getElementById("mode");
const statusLine = document.getElementById("status");

async function showStatus() {
  const state = await chrome.storage.local.get(["research", "until", "duration", "mode"]);
  research.checked = Boolean(state.research);
  duration.value = state.duration ?? "60";
  mode.value = state.mode ?? "auto";
  const writing = !state.research && (state.mode ?? "auto") === "auto" &&
    (await chrome.runtime.sendMessage({ type: "writing" }));
  if (writing) {
    statusLine.textContent = "Writing in Word: capturing articles you read.";
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

mode.addEventListener("change", () => chrome.storage.local.set({ mode: mode.value }));

document.getElementById("open-editor").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("editor/editor.html") });
});

showStatus();
