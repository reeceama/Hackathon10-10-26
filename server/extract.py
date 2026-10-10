import json
import re
from typing import Dict, List, Optional, Tuple

import trafilatura


FOOTNOTE_MARKERS = re.compile(
    r'\[(\d+|[a-z]|citation needed|note \d+)\]', re.IGNORECASE
)
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+|(?<=[.!?]["\')\]])\s+')

CITATION_LINE = re.compile(
    r'↑|\bISBN\b|\bdoi\b|Retrieved \d|Archived (from|\d)|Wayback Machine|\[edit\]',
    re.IGNORECASE,
)
MIN_SENTENCE_WORDS = 4

END_SECTIONS = {
    "references", "notes", "sources", "bibliography", "citations",
    "footnotes", "further reading", "external links", "see also",
}


def cut_end_sections(article_text: str) -> str:
    kept = []
    for line in article_text.split("\n"):
        heading = line.strip().replace("[edit]", "").strip().lower()
        if heading in END_SECTIONS:
            break
        kept.append(line)
    return "\n".join(kept)

def split_sentences(article_text: str) -> List[str]:
    article_text = cut_end_sections(FOOTNOTE_MARKERS.sub("", article_text))
    sentences = []
    for paragraph in article_text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if CITATION_LINE.search(paragraph):          # reference entries, edit links
            continue
        if len(paragraph.split()) < 8 and paragraph[-1] not in '.!?"\')]':
            continue
        sentences.extend(
            s.strip()
            for s in SENTENCE_SPLIT.split(paragraph)
            if len(s.split()) >= MIN_SENTENCE_WORDS
        )
    return sentences

def make_passages(sentences: List[str], size: int = 3, overlap: int = 1) -> List[str]:
    if not sentences:
        return []
    if len(sentences) <= size:
        return [" ".join(sentences)]
    step = size - overlap
    passages = []
    for start in range(0, len(sentences), step):
        passages.append(" ".join(sentences[start : start + size]))
        if start + size >= len(sentences):
            break
    return passages


def extract_page(
    html: str, url: Optional[str] = None
) -> Tuple[str, Dict[str, Optional[str]], List[str]]:
    """Return article text, title/author/date/URL metadata, and overlapping passages."""
    if not html.strip():
        raise ValueError("HTML must not be empty.")

    extracted = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True,
        favor_precision=True, include_tables=False,
    )
    if extracted is None:
        raise ValueError("Trafilatura could not extract an article from this HTML.")

    document = json.loads(extracted)
    if not isinstance(document, dict):
        raise ValueError("Trafilatura returned article data in an unexpected format.")

    article_text = document.get("text")
    if not isinstance(article_text, str) or not article_text.strip():
        raise ValueError("Trafilatura did not find article text in this HTML.")

    site_name = document.get("sitename")
    if not isinstance(site_name, str):
        site_name = document.get("source-hostname")

    metadata = {
        "title": document.get("title") if isinstance(document.get("title"), str) else None,
        "author": document.get("author") if isinstance(document.get("author"), str) else None,
        "date": document.get("date") if isinstance(document.get("date"), str) else None,
        "site": site_name if isinstance(site_name, str) else None,
        "url": document.get("source") if isinstance(document.get("source"), str) else url,
    }

    passages = make_passages(split_sentences(article_text))
    if not passages:
        raise ValueError("No usable passages found on this page.")
    return article_text, metadata, passages


if __name__ == "__main__":
    test_url = "https://en.wikipedia.org/wiki/Honey_bee"  # replace with a demo site
    html = trafilatura.fetch_url(test_url)
    if html is None:
        raise RuntimeError(f"Could not fetch {test_url}; choose another page to test.")

    text, meta, passages = extract_page(html, url=test_url)
    print(meta)
    print(f"{len(passages)} passages\n")
    for passage in passages[-10:]:
        print("-", passage, "\n")
