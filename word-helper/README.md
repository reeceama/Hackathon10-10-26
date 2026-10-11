# Referee Word helper

Checks the document open in Word as you write, with no add-in and no panel. When you pause, each new finished sentence is checked against your reading:

- supported claims are highlighted green and cited, and a reference list is kept at the end of the document, starting on a new page;
- contradicted claims are highlighted red, and wording problems yellow;
- every warning (misquotes, figures, mixed evidence, claims needing a source, and so on) is added as a Word comment.

Typing in Word also tells the server you're writing, so the browser extension captures what you read. While the helper is running, the Word add-in stands down so nothing is cited twice.

It works with Word for Mac (through AppleScript) and Word for Windows (through Word's COM automation). It only attaches to Word when Word is already open, and it only edits the document you're working in.

## Install

**Mac.** `sh scripts/install-server.sh` starts the server and the helper at login. The first time, macOS asks whether the helper may control Microsoft Word: allow it.

**Windows.** Install the requirements plus `pywin32` into `.venv`, then run `scripts\install-windows.bat`. It starts the server and the helper now and whenever you log in.

## Settings

`~/.referee/config.json` (created on first run):

```json
{"style": "apa", "project": ""}
```

`style` is `apa`, `harvard`, `mla`, `ieee` or `ams`. `project` limits checking to reading saved for that project; leave it empty for all reading.

## Limits

- Citations and the reference list are plain text, not Word citation fields.
- New entries are added to the end of the reference list rather than sorted into it.
- Positions are worked out from the document's text, so a sentence inside a table or next to a field may be skipped rather than risk marking the wrong text.
