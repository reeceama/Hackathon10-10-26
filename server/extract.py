import json
import re
from typing import Dict, List, Optional, Tuple

import lxml.etree
import lxml.html
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

RESULT_HEADING = re.compile(r"^(Theorem|Lemma|Proposition|Corollary|Conjecture|Definition|Claim|Assumption)\b.{0,60}$")
DISPLAYED = re.compile(r"^(\$\$|\\\[|\\begin\{)")


def join_maths(lines: List[str]) -> List[str]:

    """
    Rejoins a maths paper's statements, which pages split over several lines: "Conjecture 1" /
    "Fix d and k>0. For any S," / a displayed equation / "where ... ." would otherwise be dropped
    as too short or unfinished, losing exactly the statements worth checking against.
    """

    joined: List[str] = []
    carry = False  # the previous line continues into this one
    for line in (l.strip() for l in lines):
        if not line:
            continue
        continues = carry or DISPLAYED.match(line) or re.match(r"^(where|with|and|for|then|so that)\b", line)
        if joined and continues:
            joined[-1] += f" {line}"
        else:
            joined.append(line)
        carry = bool(RESULT_HEADING.match(line) or line.endswith((",", ":", ";")) or DISPLAYED.match(line))
    return joined


def split_sentences(article_text: str) -> List[str]:
    article_text = cut_end_sections(FOOTNOTE_MARKERS.sub("", article_text))
    sentences = []
    for paragraph in join_maths(article_text.split("\n")):
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


def keep_maths(html: str) -> str:

    """
    Replaces maths on the page with its TeX, as $...$, so it survives text extraction. Without
    this a paper's definitions and theorems lose every symbol ("Given a weighted graph , we
    define ..."). Handles MathJax 2 (TeX kept in a script), MathML with TeX alt text or annotations
    (Wikipedia, many journals) and MathJax 3's rendered output (removed: the MathML it carries is
    kept instead). TeX left in the page as \\(...\\) or $$...$$ already survives.
    """

    if not any(marker in html.lower() for marker in ("math", "mjx", "$$")):
        return html
    try:
        root = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return html

    def replace(element, tex):
        span = lxml.html.Element("span")
        span.text = f" ${' '.join(tex.split())}$ " if tex and tex.strip() else " "
        span.tail = element.tail
        element.getparent().replace(element, span)

    for container in root.xpath("//*[local-name()='mjx-container'][.//*[local-name()='math']]"):
        math = container.xpath(".//*[local-name()='math']")[0]
        math.tail = container.tail
        container.getparent().replace(container, math)
    for script in root.xpath('//script[starts-with(@type, "math/tex")]'):
        replace(script, script.text or "")
    for math in root.xpath("//*[local-name()='math']"):
        if math.getparent() is None:
            continue
        annotation = math.xpath(".//*[local-name()='annotation'][contains(@encoding, 'tex')]")
        tex = math.get("alttext") or (annotation[0].text_content() if annotation else math.text_content())
        replace(math, tex.strip().removeprefix("{\\displaystyle").removesuffix("}") if tex.strip().startswith("{\\displaystyle") else tex)
    # Rendered copies of maths now kept as TeX: MathJax 2 and 3 output and previews.
    for rendered in root.xpath('//*[contains(@class, "MathJax") or contains(@class, "MJX") or local-name()="mjx-container"]'):
        if rendered.getparent() is not None:
            rendered.drop_tree()
    # Displayed equations sit in their own boxes, which extraction treats as page furniture.
    for box in root.xpath('//div[not(.//p) and not(.//div)][starts-with(normalize-space(.), "$") or starts-with(normalize-space(.), "\\[")]'):
        box.tag = "p"
    return lxml.html.tostring(root, encoding="unicode")


def extract_page(
    html: str, url: Optional[str] = None
) -> Tuple[str, Dict[str, Optional[str]], List[str]]:
    """Return article text, title/author/date/URL metadata, and overlapping passages."""
    if not html.strip():
        raise ValueError("HTML must not be empty.")

    extracted = trafilatura.extract(
        keep_maths(html), url=url, output_format="json", with_metadata=True,
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
