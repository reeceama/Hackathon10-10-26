// Runs inside Overleaf's own page, where its editor lives (extension scripts can't reach it), and
// passes the open file's text to overleaf/checker.js whenever it changes.

(() => {
  let last = null;
  setInterval(() => {
    const content = document.querySelector(".cm-content");
    const view = content?.cmView?.rootView?.view || content?.cmView?.view;
    const text = view?.state?.doc?.toString();
    if (text == null || text === last) return;
    last = text;
    window.postMessage({ referee: "overleaf", text }, location.origin);
  }, 2000);
})();
