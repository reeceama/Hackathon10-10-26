"""Text you highlight while reading, kept as notes on its source.

The browser extension sends a highlight when you select a passage on a page it's capturing.
Highlights show in the library under their source, and passages you highlighted are tried first
when checking a claim: what you marked as important is most likely what you're citing.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List


def squash(text: str) -> str:

    return re.sub(r"\s+", " ", text or "").strip().lower()


class Highlights:

    def __init__(self, path: Path):

        self.path = path
        try:
            self.notes: Dict[str, List[Dict]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.notes = {}

    def save(self) -> None:

        self.path.write_text(json.dumps(self.notes), encoding="utf-8")

    def add(self, url: str, text: str) -> bool:

        text = re.sub(r"\s+", " ", text or "").strip()
        if len(text) < 20:
            return False
        notes = self.notes.setdefault(url, [])
        if any(squash(n["text"]) == squash(text) for n in notes):
            return False
        notes.append({"text": text[:1000], "at": time.time()})
        self.save()
        return True

    def for_url(self, url: str) -> List[Dict]:

        return self.notes.get(url, [])

    def forget(self, url: str) -> None:

        if self.notes.pop(url, None) is not None:
            self.save()

    def clear(self) -> None:

        self.notes = {}
        self.save()

    def overlaps(self, url: str, passage: str) -> bool:

        """
        Whether a passage contains (part of) something highlighted on its source.
        """

        passage = squash(passage)
        for note in self.notes.get(url, []):
            words = squash(note["text"]).split()
            # A run of eight words from the highlight is enough to match, so a highlight that
            # spans two passages still counts for both.
            for i in range(0, max(1, len(words) - 7), 4):
                if " ".join(words[i:i + 8]) in passage:
                    return True
        return False
