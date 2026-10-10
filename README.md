# Referee

**Keeps your essay honest, without playing for you.**

Referee quietly remembers the articles you read while researching. As you write, it checks
each sentence against that reading and tells you when a claim is supported, when your source
actually says the opposite, when a quotation doesn't match the source, and when you've copied
a source's wording without quoting it. It never writes for you: it only checks, credits and warns.

Built in one day for the **Invisible AI** hackathon (10 October 2026): AI that works inside what
you're already doing, rather than something you have to prompt.

---

## What it does

**While you research** (no clicks)
- Captures the articles you read, but only while **research mode** is on.
- Research mode can switch itself on when you start writing and **switches itself off** after a timer.
- Never reads private pages: banking, payment, login and account pages, email, social media,
  search results and writing tools are skipped, as is any page with a password box.
- Before anything leaves the browser tab, every form field, text box and script is stripped out,
  so nothing anyone typed is ever sent.

**While you write** (each sentence is checked when you finish it)

| Marker | Meaning |
|---|---|
| 🟩 **Supported** | A source you read backs this claim. Shows the source and the exact supporting quote. |
| 🟥 **Contradicted** | A source you read says the opposite (or a much weaker version) of your claim. |
| 🟨 **Misquote** | Text in quotation marks doesn't match the source word for word. Shows what it really says. |
| 🟨 **Too close** | Wording copied from a source without quotation marks. Ignores a topic's standard phrasing. |

If nothing you read relates to a sentence, Referee stays silent rather than guessing.

**It learns from you.** Dismiss a marker or open its source, and Referee learns which kinds of
markers you find useful, then stops showing the ones you keep rejecting. There are no settings to tune.

**What it never does**
- Write or rewrite your sentences.
- Invent a citation: every quote is checked to really appear in a source you read.
- Cite something you didn't read.

---

## How it works

```
Browser extension ──capture──▶ Backend (your laptop) ◀──check── Editor (extension page)
                                │
                                ├─ extract.py    article text → overlapping passages (trafilatura)
                                ├─ embeddings.py passages → vectors (all-MiniLM-L6-v2, runs locally)
                                ├─ store.py      saved to disk; cosine-similarity search (top 5)
                                ├─ verify.py     Claude decides supports / contradicts / neutral,
                                │                plus quote and wording checks
                                └─ feedback.py   learns which markers this person finds useful
```

1. **Capture:** the extension sends article pages to the backend, which extracts the text and
   splits it into short overlapping passages.
2. **Search:** when a sentence is finished, the closest passages are found by embedding similarity.
   This runs entirely on your machine.
3. **Verify:** Claude (`claude-haiku-5-5`, via structured outputs) judges whether any passage
   *actually* supports or contradicts the specific claim. Being on the same topic doesn't count.
   The returned quote must appear word for word in the source, or nothing is shown.
4. **Wording checks:** quotations are compared with the source (allowing `...` and `[edits]`),
   and unquoted text is checked for copied word runs, ignoring phrases that recur across your
   reading (the topic's stock phrasing).
5. **Learn:** behaviour events train a small logistic regression that decides which markers to show.

**Privacy:** your reading stays on your machine. Only the sentence being checked and its closest
matching passages are sent to Claude.

---

## Evaluation

### Claim verification: SciFact benchmark
Tested on 100 claim–evidence pairs from **SciFact**, a published scientific fact-checking dataset
(40 supporting, 30 contradicting, 30 neutral, including 15 hard "same paper, wrong sentences" cases).

| Threshold | Precision (95% Wilson CI) | Recall |
|---|---|---|
| **0.6 (chosen)** | **0.91 (0.81–0.96)** | **0.76** |
| 0.75 | 0.94 (0.84–0.98) | 0.70 |
| 0.85 | 1.00 (0.90–1.00) | 0.50 |

- **When Referee shows a marker, it's right about 91% of the time.**
- The threshold is the lowest confidence that keeps precision at or above 90%, maximising recall
  while keeping citations trustworthy.
- Errors are mostly *missed* citations rather than wrong ones, the right failure mode for this tool.
- An earlier run with the first prompt gave 0.95 (0.86–0.98). The two results sit within each
  other's confidence intervals, consistent with run-to-run variation in the model's answers.

Run it: `cd server && python eval_scifact.py build && python eval_scifact.py run && python eval_scifact.py analyse`
(needs the SciFact data in `~/scifact/data`).

### "Too close to the source" calibration
Grid search over word-run length (3–6), stock-phrase threshold and cut-off on 21 hand-labelled
sentences (copies, light edits, paraphrases and own-words sentences):

| Version | Margin between copying and own words |
|---|---|
| Plain word-run overlap | 0.06 (barely separable) |
| **Ignoring stock phrases** | **0.32 (more than five times wider)** |

Chosen: 3-word runs, stock phrase = appears in 4+ sentences of the reading, cut-off 0.30.
This is a small, hand-labelled set, so treat it as a sensible calibration rather than a benchmark.

Run it: `cd server && python eval_wording.py`

---

## Running it

### 1. Backend
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```
Create `server/.env` containing your Anthropic API key (never commit this file):
```
ANTHROPIC_API_KEY=sk-ant-...
```
Start the server:
```bash
cd server
uvicorn main:app --port 8000
```
The first start downloads the embedding model. API docs: http://localhost:8000/docs

### 2. Browser extension (Chrome)
1. Go to `chrome://extensions` and turn on **Developer mode**.
2. **Load unpacked** → select the `extension` folder.
3. Pin **Referee** (the whistle), switch on research mode, and read some articles.
4. Click the icon → **Open editor**, and start writing.

### Evaluation scripts (optional)
```bash
pip install pandas matplotlib
```

---

## API

| Endpoint | Body | Returns |
|---|---|---|
| `POST /capture` | `{url, html}` | `{ok, passages}` |
| `POST /check` | `{sentence}` | `{match: false}` or `{match: true, label, quote, source, passage, confidence, score, misquote, too_close}` |
| `POST /feedback` | `{event, sentence, url, label, confidence, score}` | `{ok}` |
| `GET /feedback` | | what the model has learned so far |
| `POST /feedback/reset` | | clears learned behaviour |
| `POST /clear` | | forgets all captured reading |

`label` is `supports`, `contradicts` or `misquote`. Feedback events: `opened_source`,
`edited_after`, `dismissed`, `ignored`.

---

## In development: Word add-in
`word-addin/` contains an add-in that brings Referee into Microsoft Word: checking sentences
as you type, APA 7 / Harvard citations using Word's own citation and bibliography tools, and
colour-coded markers that work in dark mode. **It is not yet working reliably** and isn't part
of the demo.

## What's next
- Finish the Word add-in, then Google Docs.
- Capture PDFs (many academic papers are read as PDFs).
- Reading that expires automatically after a set number of days.
- A provenance log: proof of your own research process, useful when AI-writing detectors get it wrong.
- A larger evaluation with repeated runs, real-article test pairs, and a comparison with a free local model.

---

## Team
- **sedmoh:** browser extension (research mode, page capture, editor), and the backend's
  page extraction, embeddings, storage, search and API.
- **Reece Mings-Alleyne:** claim verification, evaluation and calibration, misquote and
  copying detection, the learning model, and the Word add-in (in development).
