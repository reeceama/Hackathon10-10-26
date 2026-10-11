// Runs inside Overleaf's own page, where its editor lives (extension scripts can't reach it). It
// passes the open file's text to overleaf/checker.js whenever it changes, and moves the cursor to
// a line when the Referee panel asks.

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

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.referee !== "overleaf-goto") return;
    const view = editor();
    const line = Number(event.data.line);
    if (!view || !(line >= 1 && line <= view.state.doc.lines)) return;
    const at = view.state.doc.line(line).from;
    view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
    view.focus();
  });
})();
