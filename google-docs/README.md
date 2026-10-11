# Referee for Google Docs

A sidebar that checks the document as you write, colours each checked sentence, adds citations to supported claims and keeps a reference list at the end. Warnings (misquotes, figures, mixed evidence and so on) appear as cards in the sidebar.

Google Docs only runs add-ons while their sidebar is open, so keep it open while you write. The Referee server must be running on the same computer.

## Install (as a test add-on, for your own documents)

1. Open a Google Doc and choose **Extensions → Apps Script**.
2. Replace the contents of `Code.gs` with this folder's `Code.gs`.
3. Add two HTML files with **+ → HTML**, named `Sidebar` and `Cite`, and paste in `Sidebar.html` and `Cite.html`.
4. Under **Project Settings**, tick **Show "appsscript.json"**, then replace that file with this folder's `appsscript.json`.
5. Save, go back to the document and reload it. Open **Extensions → Referee → Open Referee**, and allow the permissions it asks for (it can only see the document it's opened in).

`Cite.html` is generated from the extension's citation styles: run `sh build.sh` after changing `extension/library/cite.js`.

| Colour | Meaning |
|---|---|
| Green | Supported, with a citation added |
| Yellow | Check the wording (misquote or too close to the source) |
| Red | A source you read says otherwise |
| Orange | Reads like a factual claim, but nothing you read supports it |

**Clear colours** removes the highlighting from the whole document, including any you added yourself.
