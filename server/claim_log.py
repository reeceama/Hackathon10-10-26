"""Claims the reading has backed or contradicted, kept on this computer.

Every confident verdict from /check is recorded, whichever app the writing is in (Word,
the browser), so the library can show which sources are cited and build the proof-of-work
report. Only the latest verdict for each sentence is kept, and only while the sentence is still in
its document: reworded or deleted sentences are dropped, so reports list what's written now.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

BIBTEX = re.compile(r"^\s*@\w+\s*\{")  # a reference file's entry, read as if it were writing


def _bare(text: str) -> str:

    """
    Letters and digits only, without citations, for finding a sentence in a document.
    """

    text = re.sub(r"\([^()]*\d{4}[^()]*\)|\[[\d,\s–-]+\]|~?\\cite\w*(\[[^\]]*\])*\{[^}]*\}", " ", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


class ClaimLog:

    """
    Sentence -> its latest verdict, saved as JSON.
    """

    def __init__(self, path: Path):

        self.path = path
        try:
            self.entries: Dict[str, Dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = {}

    def save(self) -> None:

        self.path.write_text(json.dumps(self.entries), encoding="utf-8")

    def record(self, sentence: str, verdict: Dict, project: Optional[str], document: Optional[str] = None) -> None:

        """
        Keeps the latest verdict for a sentence: supported, contradicted, a misquote, or a claim
        that needs a source, with the details the pre-submission report and research trail use.
        """

        if verdict.get("label") not in ("supports", "contradicts", "misquote", "needs_source") or BIBTEX.match(sentence):
            return
        self.entries[sentence] = {
            "sentence": sentence,
            "label": verdict["label"],
            "quote": verdict.get("quote"),
            "source": verdict.get("source"),
            "page": verdict.get("page"),
            "time": verdict.get("time"),
            "project": project,
            "document": document or self.entries.get(sentence, {}).get("document"),
            "misquote": bool(verdict.get("misquote")),
            "too_close": bool(verdict.get("too_close")),
            "wrong_numbers": verdict.get("wrong_numbers") or [],
            "changes": verdict.get("changes") or [],
            "mixed": verdict.get("mixed"),
            "together_with": verdict.get("together_with"),
            "closest": verdict.get("closest") or [],
            "at": self.entries.get(sentence, {}).get("at") or time.time(),
        }
        self.save()

    def claims(self, project: Optional[str] = None) -> List[Dict]:

        """
        Oldest first, so numbered styles can number sources in order of first citation.
        """

        found = [e for e in self.entries.values() if project is None or e["project"] in (project, None)]
        return sorted(found, key=lambda e: e["at"])

    def rename_project(self, old: str, new: Optional[str]) -> None:

        for entry in self.entries.values():
            if entry.get("project") == old:
                entry["project"] = new or None
        self.save()

    def keep_present(self, document: str, text: str) -> int:

        """
        Drops a document's claims whose sentences are no longer in its text. Returns how many.
        """

        whole = _bare(text)
        gone = [s for s, e in self.entries.items() if e.get("document") == document and _bare(s) not in whole]
        return self.forget_sentences(gone)

    def forget_sentences(self, sentences: List[str]) -> int:

        """
        Drops these sentences' claims (rewritten or deleted), and reference-file entries.
        """

        gone = [s for s in self.entries if s in set(sentences) or BIBTEX.match(s)]
        for sentence in gone:
            del self.entries[sentence]
        if gone:
            self.save()
        return len(gone)

    def forget(self, url: str) -> None:

        self.entries = {s: e for s, e in self.entries.items() if (e.get("source") or {}).get("url") != url}
        self.save()

    def clear(self) -> None:

        self.entries = {}
        self.save()
