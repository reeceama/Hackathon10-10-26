// Background service worker: talks to the backend and runs research mode.
// Pages and the editor send messages here rather than calling localhost themselves,
// which Chrome would block from ordinary web pages.

const SERVER = "http://localhost:8000";
const ROUTES = ["capture", "check", "feedback"];

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (ROUTES.includes(message.type)) {
    fetch(`${SERVER}/${message.type}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message.body),
    })
      .then((response) => response.json())
      .then(reply)
      .catch((error) => reply({ error: String(error) }));
    return true; // reply asynchronously
  }
  if (message.type === "writing") {
    fetch(`${SERVER}/writing`)
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

// Research mode: on/off, with an optional timer that switches it off automatically.
async function setResearch(on, minutes) {
  const until = on && minutes ? Date.now() + minutes * 60 * 1000 : null;
  await chrome.storage.local.set({ research: on, until });
  await chrome.alarms.clear("research-off");
  if (until) chrome.alarms.create("research-off", { when: until });
  await updateBadge();
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "research-off") setResearch(false);
});

async function updateBadge() {
  const { research } = await chrome.storage.local.get("research");
  await chrome.action.setBadgeBackgroundColor({ color: "#111111" });
  await chrome.action.setBadgeText({ text: research ? "ON" : "" });
}

chrome.runtime.onStartup.addListener(updateBadge);
chrome.runtime.onInstalled.addListener(updateBadge);
