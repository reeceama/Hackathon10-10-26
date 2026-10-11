"""BibTeX and RIS: the reference-file formats Zotero, Mendeley, EndNote and LaTeX use.

Export writes saved sources with their details. Import reads a file's entries and returns a link
for each (its URL, DOI or arXiv ID), which the server then fetches and saves like Add Source, so
Referee has each source's text to check claims against, not just its details.
"""

import re
from typing import Dict, List

import citations


def _people(source: Dict) -> List[Dict]:

    return [citations._parse_name(n) for n in citations._split_authors(source.get("author"))]


def _key(source: Dict, used: set) -> str:

    people = _people(source)
    surname = re.sub(r"[^a-z]", "", (people[0]["last"] if people else citations.clean_title(source)).lower())[:20] or "source"
    year = str(source.get("date") or "")[:4]
    word = next((w for w in re.findall(r"[a-z]+", citations.clean_title(source).lower()) if len(w) > 3), "")
    key, n = f"{surname}{year}{word}", 2
    while key in used:
        key, n = f"{surname}{year}{word}{n}", n + 1
    used.add(key)
    return key


def bibtex(sources: List[Dict]) -> str:

    entries, used = [], set()
    for s in sources:
        people = _people(s)
        journal = s.get("volume") or s.get("pages") or (s.get("doi") and s.get("type") == "pdf")
        fields = {
            "title": citations.clean_title(s),
            "author": " and ".join(f"{p['last']}, {' '.join(p['firsts'])}".strip(", ") for p in people),
            "year": str(s.get("date") or "")[:4],
            ("journal" if journal else "howpublished"): s.get("site"),
            "volume": s.get("volume"), "number": s.get("issue"), "pages": s.get("pages"),
            "doi": s.get("doi"), "url": s.get("url"), "urldate": s.get("captured_at"),
        }
        lines = [f"  {k} = {{{str(v).replace('{', '').replace('}', '')}}}" for k, v in fields.items() if v]
        entries.append(f"@{'article' if journal else 'misc'}{{{_key(s, used)},\n" + ",\n".join(lines) + "\n}")
    return "\n\n".join(entries) + "\n"


def ris(sources: List[Dict]) -> str:

    records = []
    for s in sources:
        journal = s.get("volume") or s.get("pages")
        lines = [f"TY  - {'JOUR' if journal else 'ELEC'}", f"TI  - {citations.clean_title(s)}"]
        lines += [f"AU  - {p['last']}, {' '.join(p['firsts'])}".rstrip(", ") for p in _people(s)]
        for tag, value in [("PY", str(s.get("date") or "")[:4]), ("JO" if journal else "PB", s.get("site")), ("VL", s.get("volume")),
                           ("IS", s.get("issue")), ("SP", s.get("pages")), ("DO", s.get("doi")), ("UR", s.get("url")), ("Y2", s.get("captured_at"))]:
            if value:
                lines.append(f"{tag}  - {value}")
        records.append("\n".join(lines + ["ER  - "]))
    return "\n\n".join(records) + "\n"


def entries(text: str) -> List[Dict]:

    """
    The title and a link (URL, DOI or arXiv ID) for each entry in a BibTeX or RIS file.
    """

    found = []
    if re.search(r"^TY  - ", text, re.MULTILINE):  # RIS
        for record in re.split(r"^ER  -.*$", text, flags=re.MULTILINE):
            fields: Dict[str, str] = {}
            for tag, value in re.findall(r"^([A-Z][A-Z0-9])  - (.*)$", record, re.MULTILINE):
                fields.setdefault(tag, value.strip())
            if fields:
                found.append({"title": fields.get("TI") or fields.get("T1") or "Untitled", "url": fields.get("UR"), "doi": fields.get("DO")})
    else:  # BibTeX
        for body in re.split(r"(?=@\w+\s*\{)", text):
            if not body.strip().startswith("@"):
                continue
            fields = {k.lower(): v.strip().strip("{}\"") for k, v in re.findall(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", body, re.MULTILINE)}
            arxiv = fields.get("eprint") if "arxiv" in (fields.get("archiveprefix", "") + fields.get("eprinttype", "")).lower() else None
            found.append({"title": fields.get("title") or "Untitled", "url": fields.get("url"), "doi": fields.get("doi"), "arxiv": arxiv})
    for entry in found:
        entry["link"] = (entry.get("url") or (f"https://doi.org/{entry['doi']}" if entry.get("doi") else None)
                         or (f"https://arxiv.org/pdf/{entry['arxiv']}" if entry.get("arxiv") else None))
    return found
