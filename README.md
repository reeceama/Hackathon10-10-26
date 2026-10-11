# Referee

Referee checks your writing against the sources you have read. A browser extension quietly captures the articles, PDFs and YouTube videos you read while researching, and as you write in Word, each finished sentence is checked against that reading. Supported claims are shown with the exact quote that backs them, and Referee warns you when a source says the opposite, when a quotation doesn't match its source, or when wording has been copied without quotation marks.

It never writes for you. It only checks, credits and warns.

Built in one day for the Invisible AI hackathon on 10 October 2026, where the brief was AI that works inside what you're already doing rather than something you have to prompt.

## Team members

- Reece Mings-Alleyne ([GitHub](https://github.com/reeceama) / [LinkedIn](https://www.linkedin.com/in/reece-mings-alleyne/))
- sedmoh ([GitHub](https://github.com/sedmoh))

## Contents

1. [What it does](#1-what-it-does)
2. [How it works](#2-how-it-works)
3. [Data and models](#3-data-and-models)
4. [Validation](#4-validation)
5. [Limitations](#5-limitations)
6. [Repository layout](#6-repository-layout)
7. [Running it](#7-running-it)
8. [API](#8-api)

## 1. What it does

**While you research.** Pages are captured only once you've actually read them: a page counts after it has been open and visible for 20 seconds, or as soon as you highlight text on it. Pages you bounce off aren't kept. PDFs are captured with their page numbers, and YouTube videos through their transcripts, with timestamps. By default capture runs only while you're writing in Word, or while a macOS Focus is on; it can also be switched on by hand, with a timer that switches it off again.

Captured reading is temporary: it can be cited straight away, and is forgotten after 15 minutes (or an hour, or a day) unless you keep it. **Save for later** in the popup keeps the page you're on, whether or not it was captured, and any source your writing cites is kept automatically. Kept sources belong to the current project, chosen or created in the popup. Projects are kept apart: writing is only checked against its own project's sources, plus any other projects you link it to in the library, where sources can also be moved between projects. Referee never runs in private (Incognito) windows. The popup lists your reading, saved or temporary, and lets you forget any source.

Banking, payment, login and account pages, email, social media, search results and writing tools are never captured, nor is any page with a password box. Before a page leaves the browser tab, every form field, text box and script is removed, so nothing anyone typed is sent.

**While you write.** Each sentence is checked when it is finished, whether or not research mode is on. Research mode controls what is captured; anything already captured can be checked against at any time.

| Marker | Meaning |
|---|---|
| Supported | A source you read backs this claim, shown with the exact supporting quote. |
| Contradicted | A source you read says the opposite, or a much weaker version, of the claim. |
| Misquote | Text in quotation marks doesn't match the source word for word. |
| Too close | Wording copied from a source without quotation marks. |
| Needs a source | Reads like a factual claim, but nothing you read supports it. The closest sources you've read are suggested as places to look. |

Referee also warns when a figure in the sentence isn't in the source, show exactly which words of a misquote differ, note when another source you read points the other way, when a claim only holds by combining two sources, and when a supporting source is more than ten years old. The library summarises how many claims your reading backs, and flags leaning heavily on one source.

In Word, the background Word helper (macOS and Windows) checks as you type with no add-in or panel: supported claims are highlighted and cited, a reference list is kept at the end, and warnings become comments. The Word add-in does the same from a panel, and stands down while the helper runs; it adds citations and a reference list through Word's own source manager, so they can be edited with Word's References tools, and warnings appear as comments. The extension's library lists everything you've read, which sources your writing cites, and the reference list in APA 7, Harvard, MLA 9, IEEE or AMS, with page numbers for PDFs and timestamps for videos. Its proof-of-work report lists what you read, when, and which claims it backs.

If a sentence makes no claim and nothing you read relates to it, Referee stays silent rather than guessing.

**It learns from behaviour.** Dismissing a marker or opening its source is recorded, and Referee learns which kinds of marker each person finds useful, then stops showing the ones they keep rejecting. There is nothing to configure.

## 2. How it works

```
Browser extension ──capture──▶ Backend (your laptop) ◀──check── Word
                                │
                                ├─ extract.py    article text → overlapping passages
                                ├─ pdf.py        PDF text, with page numbers
                                ├─ video.py      YouTube transcripts, with timestamps
                                ├─ embeddings.py passages → vectors (runs locally)
                                ├─ store.py      saved to disk; meaning and keyword search
                                ├─ claims.py     does an unsupported sentence need a source?
                                ├─ verify.py     Claude: supports / contradicts / neutral,
                                │                plus quote and copying checks
                                └─ feedback.py   learns which markers each person finds useful
```

**Capture.** The extension sends each article page to a local backend, which extracts the article text with trafilatura, strips references and citation clutter, and splits it into short overlapping passages.

**Search.** Passages are embedded with a small sentence-embedding model that runs on your own machine. A finished sentence is embedded the same way and compared by cosine similarity, and a BM25 keyword search runs alongside it, since meaning-based search can blur exact names and figures. The two rankings are combined by reciprocal rank fusion, and the top five passages are taken forward, provided they clear a minimum similarity. If none do, nothing is sent anywhere.

**Verify.** Claude decides whether any of those passages supports or contradicts the specific claim, or neither. Being on the same topic is not support, and the strength of a claim counts, so "strongly linked" is contradicted by a source that finds only a weak link. The reply is constrained to a fixed schema with structured outputs. The quote it returns must be at least four words and appear in the passage (ignoring differences in spacing, capitals and curly quotes), otherwise nothing is shown. Calls time out after 10 seconds, and failures are logged. Verdicts are cached, so re-checking the same sentence against the same passages costs nothing.

**Wording checks.** Quotations are compared with the source, treating `...` and `[insertions]` as gaps. Unquoted text is checked for copied wording by the share of its 3-word runs found in the passage, ignoring runs that recur across four or more sentences of the reading, since those are stock phrasing rather than copying from one source.

**Learning.** Behaviour events become labelled examples, with explicit actions weighted fully and implicit ones weighted less. A logistic regression on verifier confidence, search similarity and marker type is refitted after every event. Until there are enough events to cover both outcomes, every marker the verifier accepts is shown, so the evaluated threshold acts as the prior.

**Privacy.** Only the sentence being checked and its closest passages are sent to Claude. The reading itself stays on your machine.

## 3. Data and models

| Source | Use |
|---|---|
| SciFact | 1,409 scientific claims with labelled evidence from 5,183 abstracts, used to evaluate the verifier |
| trafilatura | Article text extraction from captured pages |
| all-MiniLM-L6-v2 (ONNX) | Local sentence embeddings for search, run with ONNX Runtime |
| Claude Haiku 5.5 | Claim verification, through the Anthropic API |
| Wikipedia, NHS and BBC pages | Captured during development and used for the wording calibration |

SciFact is not committed to this repository. The evaluation script expects it in `~/scifact/data`.

## 4. Validation

Every figure in this section is reproduced by `eval_scifact.py` and `eval_wording.py` in `server/`.

### Claim verification

100 claim and evidence pairs were drawn from the SciFact development set: 40 supporting, 30 contradicting, 15 claims paired with an abstract they cite but that doesn't address them, and 15 claims paired with sentences from their own evidence abstract that aren't the evidence. The last group is the hard case: same topic, same paper, but no support.

The verifier was run on every pair with its threshold switched off, then scored at each confidence level. A marker counts as shown when the verdict is supported or contradicted at or above the threshold.

| Threshold | Precision | 95% CI | Recall | Markers shown |
|---|---|---|---|---|
| 0.60 | 0.93 | 0.83–0.97 | 0.76 | 57 |
| **0.70 (chosen)** | **0.96** | **0.87–0.99** | **0.70** | 51 |
| 0.80 | 0.98 | 0.88–1.00 | 0.63 | 45 |
| 0.85 | 1.00 | 0.89–1.00 | 0.46 | 32 |

Intervals are Wilson score intervals. To choose the threshold, a logistic regression of whether a marker was correct on the verifier's confidence was fitted by maximum likelihood, pooling this run with the previous one (117 markers). Treating a wrong marker as three times as costly as a missed one, a marker should be shown when it is at least 75% likely to be right, which the fit puts at a confidence of 0.68 (bootstrap 90% range 0.61–0.73). 0.7 is the nearest round value.

| True label ↓ / verdict → | contradicts | neutral | supports |
|---|---|---|---|
| contradicts | 24 | 6 | 0 |
| neutral | 3 | 27 | 0 |
| supports | 3 | 8 | 29 |

Verdicts before any threshold. Most errors are missed support rather than false support, which is the safer way for a citation tool to be wrong.

Earlier runs with previous versions of the prompt gave precisions of 0.91 and 0.95 at a threshold of 0.6. They sit inside each other's intervals, which is consistent with run-to-run variation in the model's answers rather than real differences between the prompts.

### Copying detection

21 sentences were written against five passages from the captured Wikipedia article on the Mediterranean diet: copies, light edits, paraphrases and sentences in the writer's own words. The check should flag the first two and not the last two. A grid over run length, stock-phrase threshold and cut-off finds the setting with the widest gap between them.

| Setting | Margin |
|---|---|
| Word-run overlap only | 0.06 |
| Ignoring stock phrases | 0.32 |

Ignoring stock phrasing widened the margin more than five times. The chosen setting is 3-word runs, stock phrases appearing in 4 or more sentences of the reading, and a cut-off of 0.30.

## 5. Limitations

- **The intervals are wide.** 100 pairs gives a precision interval of roughly 87% to 99%. At the low end, about one marker in eight would be wrong.
- **The threshold was chosen on the same pairs it is reported on,** so the figures are slightly optimistic. A fairer test would choose it on half the pairs and report on the other half.
- **Answers vary between runs.** The model doesn't accept a sampling temperature, so the same sentence can occasionally get a different verdict. The evaluation measures behaviour across many cases rather than relying on any single answer.
- **SciFact is not the web.** The benchmark is scientific abstracts. Everyday articles may behave differently, and that hasn't been tested yet.
- **The copying calibration is small:** 21 hand-written sentences from one article. It is a sensible setting, not a benchmark. Which phrases count as stock depends on what has been captured, so it should be rerun on a wider set of reading.
- **Only double quotation marks are read as quotes.** Single quotes are skipped because they look the same as apostrophes, and square brackets inside a quote are accepted as edits without checking what they replace.
- **Scanned PDFs and videos without captions can't be read.** Spoken transcripts also match written sentences less closely than articles do.
- **The extra checks are rules of thumb.** Whether a sentence needs a source, and what counts as an old source or over-reliance, are simple rules, not evaluated models.
- **Author metadata is unreliable.** Many pages don't publish a usable author, so the organisation is used instead.
- **Learning starts from very little.** With only a handful of events the model is easily swayed, which is why it falls back to the evaluated threshold until it has seen both outcomes. Referee doesn't report "ignored" markers: with an invisible tool, leaving a correct marker alone is the normal case, so it isn't evidence the marker was unhelpful.
- **The skip list is a list.** It covers major banks, payment, login and account pages, but it can't name every private site. The password-box rule catches most of the rest.

## 6. Repository layout

```
├── referee.py                  starts and watches the background parts (macOS and Windows)
├── tests/smoke_test.py         checks the background parts work, run by GitHub on Windows and macOS
├── server/                     backend, runs locally
│   ├── main.py                 API routes
│   ├── extract.py              article text and passages
│   ├── pdf.py                  PDF text and page numbers
│   ├── video.py                YouTube transcripts and timestamps
│   ├── embeddings.py           local sentence embeddings
│   ├── keywords.py             BM25 keyword search
│   ├── store.py                passage storage and search
│   ├── claims.py               does a sentence need a source?
│   ├── verify.py               claim verification, quote, figure and copying checks
│   ├── feedback.py             learns which markers each person finds useful
│   ├── claim_log.py            claims each source has backed, for the library
│   ├── reading.py              projects, and how long unsaved reading is kept
│   ├── citations.py            citation styles for the Word helper
│   ├── eval_scifact.py         verifier evaluation on SciFact
│   ├── eval_wording.py         copying detection calibration
│   ├── load_demo.py            preloads demo sources
│   ├── .env.example            copy to .env and add your API key
│   └── requirements.txt
│
├── extension/                  Chrome extension
│   ├── manifest.json
│   ├── background.js           talks to the backend, runs research mode
│   ├── content.js              captures article pages once they've been read
│   ├── skip.js                 pages that are never captured
│   ├── popup/                  research mode, projects, captured reading
│   ├── library/                captured reading, references, proof of work
│   ├── dev/editor/             developer test page for checks (not user facing)
│   └── icons/
│
├── macapp/                     Referee for Mac: menu bar app that runs the server and Word helper
├── word-helper/                background Word helper (AppleScript on macOS, COM on Windows)
├── word-addin/                 Word add-in (fallback)
│
├── README.md
└── .gitignore
```

## 7. Running it

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt
```

Add your Anthropic API key in Referee's settings (the Mac app, or the extension's library on any system). It's checked with Anthropic, then kept in your computer's password store (Keychain or Credential Manager). Alternatively, copy `server/.env.example` to `server/.env` and put the key there. Never commit that file.

```
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
# start everything: the server, the Word helper and (with its certificates) the Word add-in's
# server. The first run downloads the embedding model (about 90 MB).
python referee.py

# or just the server
cd server
uvicorn main:app --port 8000

# verifier and wording tests
python verify.py

# evaluation: needs pandas and matplotlib, and SciFact in ~/scifact/data
python eval_scifact.py build
python eval_scifact.py run
python eval_scifact.py analyse
python eval_wording.py
```

On a Mac, `sh macapp/build.sh` builds **Referee.app** and installs it in `~/Applications`. It lives in the menu bar (a whistle: outlined when idle, filled while capturing), runs the server, the Word helper and the Word add-in's HTTPS server while it's open, and has a settings window for the project, how long unsaved reading is kept, the citation style in Word and opening at login. On Windows, `scripts\install-windows.bat` starts the server and Word helper at login. `tests/smoke_test.py` checks the background parts work, without Word or an API key; GitHub runs it on Windows and macOS after every push. See `word-helper/README.md`.

To switch research mode on with a macOS Focus, create two automations in the Shortcuts app: when the Focus turns on, run the shell script `curl -s -X POST localhost:8000/focus -H 'Content-Type: application/json' -d '{"on":true}'`, and when it turns off, the same with `false`.

To load the extension, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked** and select the `extension` folder. Start writing in Word and read some sources; anything you read while writing is captured. Open the library from the popup to see your reading and references. API docs are at http://localhost:8000/docs while the backend is running.

## 8. API

| Endpoint | Body | Returns |
|---|---|---|
| `POST /capture` | `{url, html, project}` | `{ok, passages}` |
| `POST /capture-pdf` | `{url, data, title, project}` (PDF as base64) | `{ok, passages}` |
| `POST /capture-video` | `{url, project}` | `{ok, passages}` |
| `POST /check` | `{sentence, project}` | `{match: false, needs_source, closest}` or `{match: true, label, quote, source, passage, page, time, confidence, score, misquote, too_close, changes, wrong_numbers, mixed, together_with}` |
| `GET /sources`, `DELETE /sources?url=` | | lists captured sources, or forgets one |
| `GET /claims?project=` | | claims the reading has backed or contradicted, oldest first |
| `POST /focus` | `{on}` | switches research mode on or off (macOS Focus) |
| `POST /sources/keep` | `{url, project}` | keeps a source (save for later) |
| `POST /sources/move` | `{url, project}` | moves a source to another project |
| `GET /settings`, `POST /settings` | `{project, projects, keep_minutes, links}` | current project, project list, how long unsaved reading is kept |
| `POST /helper` | | heartbeat from the Word helper, so the add-in stands down |
| `POST /feedback` | `{event, sentence, url, label, confidence, score}` | `{ok}` |
| `GET /feedback` | | what the model has learned so far |
| `POST /feedback/reset` | | clears learned behaviour |
| `POST /writing`, `GET /writing` | | marks or reports an active writing session (automatic mode) |
| `POST /clear` | | forgets all captured reading |

`label` is `supports`, `contradicts` or `misquote`. Feedback events are `opened_source`, `edited_after`, `dismissed` and `ignored`.
