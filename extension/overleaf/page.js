// Runs inside Overleaf's own page, where its editor lives (extension scripts can't reach it). It
// passes the open file's text to overleaf/checker.js whenever it changes, moves the cursor to a
// line when the Referee panel asks, and inserts citations (as an ordinary edit, so Overleaf syncs
// and records it like typing).

(() => {
  let last = null;
  const editor = () => {
    const content = document.querySelector(".cm-content");
    return content?.cmView?.rootView?.view || content?.cmView?.view;
  };

  setInterval(() => {
    const text = editor()?.state?.doc?.toString();
    if (text == null || text === last) return;
    last = text;
    window.postMessage({ referee: "overleaf", text }, location.origin);
  }, 2000);

  const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // "~\cite{key}" just before the sentence's final punctuation. The sentence is found from the
  // line it starts on and its last word. Automatic insertions skip the sentence being edited.
  function insert({ line, sentence, key, auto }) {
    const view = editor();
    if (!view) return "no editor";
    const doc = view.state.doc;
    const start = doc.line(Math.min(Math.max(Number(line) || 1, 1), doc.lines)).from;
    const last = sentence.replace(/["”’')\].!?]+$/, "").split(/\s+/).pop();
    const text = doc.sliceString(start, Math.min(doc.length, start + sentence.length * 2 + 400));
    // Any citations already at the end of the sentence are stepped over: "homology~\cite{a}."
    const end = new RegExp(`${escape(last)}[}$)\\s]*(?:~?\\\\cite\\w*(?:\\[[^\\]]*\\])*\\{[^}]*\\}\\s*)*([.!?])`).exec(text);
    if (!end) return "sentence not found";
    const at = start + end.index + end[0].length - 1;
    if (new RegExp(`\\\\cite\\w*(\\[[^\\]]*\\])*\\{[^}]*\\b${escape(key)}\\b`).test(text.slice(0, at - start))) return "already cited";
    const cursor = view.state.selection.main.head;
    if (auto && view.hasFocus && cursor >= start - 1 && cursor <= at + 2) return "editing";
    view.dispatch({ changes: { from: at, insert: `~\\cite{${key}}` } });
    return "ok";
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (event.data?.referee === "overleaf-insert") {
      const outcome = insert(event.data);
      window.postMessage({ referee: "overleaf-inserted", id: event.data.id, outcome }, location.origin);
      return;
    }
    if (event.data?.referee !== "overleaf-goto") return;
    const view = editor();
    const line = Number(event.data.line);
    if (!view || !(line >= 1 && line <= view.state.doc.lines)) return;
    const at = view.state.doc.line(line).from;
    view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
    view.focus();
  });
})();
