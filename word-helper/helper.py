"""Referee for Word, running in the background: no add-in and no panel.

Every few seconds it reads the document open in Word. Once you pause, each new finished
sentence is checked against your reading; supported claims are highlighted and cited,
problems get a comment, and the reference list at the end is kept up to date. Typing also
tells the server you're writing, so the browser extension captures what you read.

Run: python word-helper/helper.py   (it attaches to Word when Word is open)
Settings: ~/.referee/config.json, {"style": "apa" | "harvard" | "mla" | "ieee" | "ams"}.
The project is the current one chosen in the browser extension.
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import citations  # noqa: E402  shared with the server, so styles match everywhere

SERVER = "http://localhost:8000"
HEADERS = {"X-Referee": "1"}
POLL_SECONDS = 4          # how often the document is read
PING_SECONDS = 60         # "still writing" signals, at most this often
MIN_WORDS = 5
OLD_SOURCE_YEARS = 10
COMMENT_PREFIX = "Referee: "
HEADINGS = {"References", "Reference list", "Works Cited"}
SENTENCE = re.compile(r"[^.!?\r\n]+[.!?]+[\"”’)\]]*")
CLOSING = re.compile(r"[.!?]+[\"”’)\]]*$")
HOME = Path.home() / ".referee"


class Settings:

    """
    Style and project from ~/.referee/config.json, created with defaults on first run.
    """

    def __init__(self):

        self.path = HOME / "config.json"
        if not self.path.exists():
            HOME.mkdir(exist_ok=True)
            self.path.write_text(json.dumps({"style": "apa"}, indent=2), encoding="utf-8")

    def load(self) -> Dict:

        try:
            settings = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        style = settings.get("style", "apa")
        # An empty project means the server's current project, chosen in the browser extension.
        return {"style": style if style in citations.HEADINGS else "apa", "project": settings.get("project", "")}


class DocumentState:

    """
    Per document: sentences already checked, the sources cited and their numbers.
    Saved in ~/.referee/word-helper.json so restarting doesn't re-check everything.
    """

    def __init__(self):

        self.path = HOME / "word-helper.json"
        try:
            self.documents: Dict[str, Dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.documents = {}

    def get(self, name: str) -> Dict:

        state = self.documents.setdefault(name, {})
        state.setdefault("checked", [])
        state.setdefault("cited", {})     # url -> source metadata
        state.setdefault("numbers", {})   # url -> number, for numbered styles
        state.setdefault("listed", [])    # reference entries already in the document
        return state

    def save(self) -> None:

        HOME.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.documents), encoding="utf-8")


def writing_part(text: str) -> str:

    """
    The document up to its reference list heading.
    """

    position = 0
    for line in re.split(r"[\r\n]", text):  # paragraphs end in \r (osascript reports \n)
        if line.strip() in HEADINGS:
            return text[:position]
        position += len(line) + 1
    return text


def finished_sentences(text: str) -> List[Dict]:

    """
    Every finished sentence long enough to carry a claim, with its position.
    """

    found = []
    for match in SENTENCE.finditer(writing_part(text)):
        sentence = match.group().strip()
        if len(sentence.split()) < MIN_WORDS:
            continue
        start = match.start() + (len(match.group()) - len(match.group().lstrip()))
        found.append({"sentence": sentence, "start": start, "end": start + len(sentence)})
    return found


def notes_for(result: Dict) -> List[str]:

    """
    The comments a verdict deserves, the same wording as the other Referee apps.
    """

    if not result.get("match"):
        if not result.get("needs_source"):
            return []
        closest = "; ".join(citations.clean_title(c) for c in result.get("closest") or [])
        return ["This reads like a factual claim, but nothing you've read supports it yet."
                + (f" Closest in your reading: {closest}." if closest else "")]
    notes = []
    source = result.get("source") or {}
    if result["label"] == "contradicts":
        notes.append(f"Your source says otherwise: \"{result.get('quote')}\" ({citations.clean_title(source)})")
    if result.get("misquote"):
        notes.append(f"This quotation doesn't match the source exactly. The source says: \"{result.get('quote')}\"")
    if result.get("too_close"):
        notes.append("Very close to the source's wording. Consider quoting it or rephrasing.")
    for change in (result.get("changes") or [])[:3]:
        if change.get("wrote") and change.get("source"):
            notes.append(f"You quoted \"{change['wrote']}\"; the source says \"{change['source']}\".")
        elif change.get("wrote"):
            notes.append(f"\"{change['wrote']}\" isn't in the source's wording.")
        else:
            notes.append(f"You left out \"{change['source']}\".")
    for figure in result.get("wrong_numbers") or []:
        notes.append(f"\"{figure}\" doesn't appear in the source. Check the figure.")
    if result.get("together_with"):
        notes.append(f"This claim combines two sources: also cite {citations.clean_title(result['together_with'].get('source') or {})}.")
    if result.get("mixed"):
        notes.append(f"Mixed evidence: {citations.clean_title(result['mixed'])} points the other way.")
    year = re.match(r"\d{4}", str(source.get("date") or ""))
    if result["label"] == "supports" and year and time.localtime().tm_year - int(year.group()) > OLD_SOURCE_YEARS:
        notes.append(f"This source is from {year.group()}. Check whether newer evidence agrees.")
    return [COMMENT_PREFIX + note for note in notes]


class Helper:

    def __init__(self, word):

        self.word = word
        self.settings = Settings()
        self.state = DocumentState()
        self.last_text: Optional[str] = None
        self.last_ping = 0.0
        self.last_heartbeat = 0.0

    def post(self, path: str, body: Dict) -> Optional[Dict]:

        try:
            return requests.post(f"{SERVER}{path}", json=body, headers=HEADERS, timeout=30).json()
        except (requests.RequestException, ValueError):
            return None

    def step(self) -> None:

        if not self.word.available():
            self.last_text = None
            return
        # Tell the Word add-in to stay quiet, so the two never mark the same document.
        if time.time() - self.last_heartbeat > PING_SECONDS / 2:
            self.last_heartbeat = time.time()
            self.post("/helper", {})

        document = self.word.document()
        if document is None:
            return
        name, text = document
        if text != self.last_text:
            # Still typing: note it, and wait for a pause before checking anything.
            if self.last_text is not None and time.time() - self.last_ping > PING_SECONDS:
                self.last_ping = time.time()
                self.post("/writing", {})
            self.last_text = text
            return
        self.check(name, text)

    def check(self, name: str, text: str) -> None:

        settings = self.settings.load()
        state = self.state.get(name)
        checked = set(state["checked"])
        fresh = [s for s in finished_sentences(text) if s["sentence"] not in checked]
        if not fresh:
            return

        results = []
        for item in fresh:
            result = self.post("/check", {"sentence": item["sentence"], "project": settings["project"]})
            if result is None:
                return  # server not running: try again on the next pause
            results.append((item, result))

        # Edit from the end of the document backwards, so earlier positions stay valid.
        existing = {(start, note) for start, _, note in self.word.comments()}
        for item, result in sorted(results, key=lambda pair: -pair[0]["start"]):
            sentence, start, end = item["sentence"], item["start"], item["end"]
            if self.word.text_at(start, end) != sentence:
                continue  # the document moved under us: leave it for the next pause
            checked.add(sentence)
            for note in notes_for(result):
                if (start, note) not in existing:
                    self.word.comment(start, end, note)
            if not result.get("match"):
                continue
            label = result["label"]
            warn = label == "misquote" or (label == "supports" and (result.get("misquote") or result.get("too_close")))
            self.word.mark(start, end, "warn" if warn else label if label in ("supports", "contradicts") else "warn")
            if label == "supports":
                cited = self.cite(state, settings["style"], result)
                if cited not in sentence:
                    punctuation = CLOSING.search(sentence)
                    position = end - (len(punctuation.group()) if punctuation else 0)
                    self.word.insert(position, f" {cited}")
                    checked.add(sentence[:position - start] + f" {cited}" + sentence[position - start:])

        state["checked"] = sorted(checked)
        self.update_references(state, settings["style"])
        self.state.save()
        document = self.word.document()
        self.last_text = document[1] if document else None  # our own edits aren't typing

    def cite(self, state: Dict, style: str, result: Dict) -> str:

        source = result.get("source") or {}
        url = source.get("url") or citations.clean_title(source)
        state["cited"][url] = source
        state["numbers"].setdefault(url, len(state["numbers"]) + 1)
        return citations.in_text(style, source, number=state["numbers"][url],
                                 page=result.get("page"), time=result.get("time"))

    def update_references(self, state: Dict, style: str) -> None:

        """
        Adds entries for newly cited sources under a reference heading at the end.
        """

        sources = list(state["cited"].items())
        if style in citations.NUMBERED:
            sources.sort(key=lambda pair: state["numbers"][pair[0]])
        else:
            sources.sort(key=lambda pair: citations.sort_key(pair[1]))
        entries = [citations.reference(style, source, number=state["numbers"][url]) for url, source in sources]
        new = [entry for entry in entries if entry not in state["listed"]]
        if not new:
            return
        document = self.word.document()
        if document is None:
            return
        has_heading = any(line.strip() in HEADINGS for line in re.split(r"[\r\n]", document[1]))
        block = "\r".join(new)
        if not has_heading:
            block = "\x0c" + citations.HEADINGS[style] + "\r" + block  # page break, then the heading
        self.word.append("\r" + block)
        state["listed"].extend(new)


def driver():

    if sys.platform == "darwin":
        from mac import MacWord
        return MacWord()
    if sys.platform == "win32":
        from windows import WindowsWord
        return WindowsWord()
    raise SystemExit("The Word helper runs on macOS and Windows.")


def main() -> None:

    helper = Helper(driver())
    print("Referee Word helper running. It checks the document open in Word as you write.")
    while True:
        try:
            helper.step()
        except Exception as error:  # Word busy, a dialog open, a document closing: try again
            print(f"[helper] {type(error).__name__}: {error}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
