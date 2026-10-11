"""Claims the reading has backed or contradicted, kept on this computer.

Every confident verdict from /check is recorded, whichever app the writing is in (Word,
Obsidian), so the library can show which sources are cited and build the proof-of-work
report. Only the latest verdict for each sentence is kept.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional


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

    def record(self, sentence: str, verdict: Dict, project: Optional[str]) -> None:

        if verdict.get("label") not in ("supports", "contradicts"):
            return
        self.entries[sentence] = {
            "sentence": sentence,
            "label": verdict["label"],
            "quote": verdict.get("quote"),
            "source": verdict.get("source"),
            "page": verdict.get("page"),
            "time": verdict.get("time"),
            "project": project,
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

    def forget(self, url: str) -> None:

        self.entries = {s: e for s, e in self.entries.items() if (e.get("source") or {}).get("url") != url}
        self.save()

    def clear(self) -> None:

        self.entries = {}
        self.save()
