const research = document.getElementById("research");
const duration = document.getElementById("duration");
const mode = document.getElementById("mode");
const statusLine = document.getElementById("status");
const savedList = document.getElementById("saved-list");
const savedTitle = document.getElementById("saved-title");
const savedEmpty = document.getElementById("saved-empty");
const server = document.getElementById("server");
const projectInput = document.getElementById("project");
const projectList = document.getElementById("projects");
const expiry = document.getElementById("expiry");
const searchBox = document.getElementById("search");

// A rough guide to what kind of source a page is, from its address.
const SOURCE_TYPES = [
  ["Academic", /\.(ac\.uk|edu)(\/|$)|doi\.org|arxiv\.org|jstor|springer|sciencedirect|wiley|nature\.com|ncbi\.nlm|pubmed|researchgate|semanticscholar|tandfonline|sagepub|\.pdf($|[?#])/i],
  ["Government", /\.gov(\.[a-z]{2})?(\/|$)|\.gov\.uk|nhs\.uk|who\.int|europa\.eu|\.mod\.uk|ons\.gov/i],
  ["News", /bbc\.|theguardian|nytimes|reuters|apnews|ft\.com|economist|independent\.co|telegraph|washingtonpost|cnn\.com|sky\.com|aljazeera/i],
  ["Encyclopedia", /wikipedia\.org|britannica\.com/i],
  ["Blog or forum", /medium\.com|substack|wordpress|blogspot|reddit|quora|stackexchange|stackoverflow|tumblr/i],
];
function sourceType(url) {
  const found = SOURCE_TYPES.find(([, pattern]) => pattern.test(url || ""));
  return found ? found[0] : "Website";
}

const CAPTURE_STATUS = {
  saved: (c) => `Saved · ${c.passages} passages`,
  already: () => "Already saved",
  skipped: (c) => `Not saved: ${c.reason || "no article text found"}`,
  offline: () => "Not saved: the server wasn't running",
};

// The pages Referee has captured, most recent first, filtered by the search box.
async function showSaved() {
  const { captures = [] } = await chrome.storage.local.get("captures");
  // Sources that have backed a claim in Word or Obsidian, from the server's claim log.
  const claims = await chrome.runtime.sendMessage({ type: "get", path: "claims" }).catch(() => []);
  const cited = Array.isArray(claims)
    ? claims.filter((c) => c.label === "supports").map((c) => c.source?.url).filter(Boolean) : [];
  const query = searchBox.value.trim().toLowerCase();
  const shown = captures.filter((c) => !query || `${c.title} ${c.url} ${c.project || ""}`.toLowerCase().includes(query));
  savedList.replaceChildren(...shown.slice(0, 30).map((c) => {
    const item = document.createElement("li");
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = c.title;
    title.title = c.url;
    const status = document.createElement("span");
    status.className = "s";
    status.dataset.status = c.status;
    status.textContent = (CAPTURE_STATUS[c.status] || (() => c.status))(c);
    const tags = document.createElement("div");
    tags.className = "tags";
    const addTag = (text, extra = "") => {
      const tag = document.createElement("span");
      tag.className = `tag ${extra}`;
      tag.textContent = text;
      tags.append(tag);
    };
    if (c.status === "saved" || c.status === "already") {
      addTag(sourceType(c.url));
      if (c.project) addTag(c.project);
      addTag(cited.includes(c.url) ? "Cited" : "Not cited yet", cited.includes(c.url) ? "cited" : "");
    }
    const forget = document.createElement("button");
    forget.className = "forget-one";
    forget.title = "Forget this page";
    forget.textContent = "×";
    forget.addEventListener("click", () => chrome.runtime.sendMessage({ type: "forget", url: c.url }));
    item.append(title, status, tags, forget);
    return item;
  }));
  const saved = captures.filter((c) => c.status === "saved").length;
  savedTitle.textContent = saved ? `Saved pages (${saved})` : "Saved pages";
  savedEmpty.hidden = captures.length > 0;
}

searchBox.addEventListener("input", showSaved);

// Reading is kept per project, so one piece of work never cites another's reading.
async function showProject() {
  const { project = "", projects = [], expiryDays = "0" } = await chrome.storage.local.get(["project", "projects", "expiryDays"]);
  projectInput.value = project;
  projectList.replaceChildren(...projects.map((name) => Object.assign(document.createElement("option"), { value: name })));
  expiry.value = String(expiryDays);
}

projectInput.addEventListener("change", async () => {
  const project = projectInput.value.trim();
  const { projects = [] } = await chrome.storage.local.get("projects");
  await chrome.storage.local.set({ project, projects: project && !projects.includes(project) ? [...projects, project] : projects });
  showProject();
});

expiry.addEventListener("change", async () => {
  await chrome.storage.local.set({ expiryDays: expiry.value });
  chrome.runtime.sendMessage({ type: "expire" });
});

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

document.getElementById("open-library").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("library/library.html") });
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
showProject();
showServer();
