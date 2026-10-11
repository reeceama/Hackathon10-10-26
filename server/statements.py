"""Checks theorems and definitions taken from papers against the papers themselves.

Mathematical writing restates results from the literature: "Theorem 2.3 (\\cite{bobrowski2023cluster}).
Let G be a finite weighted graph...". The common mistake is a dropped or changed condition, or a
stronger conclusion than the paper proves. Here the cited paper's closest passages are found and
Claude compares the two statements. It only points at differences: it never writes or fixes maths.
"""

import hashlib
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

import bib
from store import search, sources
from verify import anthropic_client, MODEL

PASSAGES = 4

SYSTEM = """You compare a mathematical statement in a person's writing with the paper it cites.

You get the writer's statement (LaTeX) and numbered passages from the cited paper (text extracted
from a PDF, so its mathematical notation may be garbled). Find the passage stating the same
theorem, lemma, proposition, corollary, conjecture or definition, if there is one. Papers often
state several related results (e.g. a weak and a strong version, or Conjecture 1 and Conjecture 2):
choose the one whose hypotheses and conclusion match the writer's most closely, and use the
writer's label (e.g. "Conjecture 1") if one is given. If the writer's statement matches one
result, report no differences, even if it differs from the others.

Then list only real mathematical differences:
- missing_condition: the paper assumes something the writer left out (e.g. finite, connected, p > 1).
- extra_condition: the writer assumes something the paper doesn't (harmless but worth knowing).
- different_conclusion: the writer claims something stronger, weaker or different.
- other: anything else that changes the meaning, e.g. a different constant, quantifier or bound.

Different notation, variable names, wording or order are NOT differences. If unsure whether
something is a real difference, leave it out. Never suggest how to fix or prove anything.
Give "quote" as the paper's statement, cleaned up to be readable."""


class Difference(BaseModel):
    kind: Literal["missing_condition", "extra_condition", "different_conclusion", "other"]
    detail: str


class Comparison(BaseModel):
    passage: Optional[int]      # the passage stating the same result, or None if none does
    quote: str
    differences: List[Difference]


_cache: Dict[str, Dict] = {}


def check(statement: str, kind: str, keys: List[str], label: str = "") -> Dict:

    """
    Compares a statement with the saved papers it cites, by citation key.
    """

    by_key = {key: url for url, key in bib.keys(sources()).items()}
    urls = {by_key[k] for k in keys if k in by_key}
    if not urls:
        return {"found": False, "reason": "not_saved"}
    passages = search(statement, k=PASSAGES, urls=urls)
    if not passages:
        return {"found": False, "reason": "not_saved"}
    numbered = "\n\n".join(f"[{i}] {p['text']}" for i, p in enumerate(passages))
    named = f" (the writer labels it: {label})" if label else ""
    user = f"Writer's {kind}{named}:\n{statement}\n\nPassages from the cited paper:\n{numbered}"
    key = hashlib.sha256(user.encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    client = anthropic_client.get()
    if client is None:
        return {"found": False, "reason": "no_api_key"}
    response = client.messages.parse(
        model=MODEL, max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}], output_format=Comparison)
    comparison = response.parsed_output
    if comparison is None:
        return {"found": False, "reason": "failed"}
    if comparison.passage is None or not 0 <= comparison.passage < len(passages):
        result = {"found": False, "reason": "not_in_paper", "source": passages[0]["source"]}
    else:
        chosen = passages[comparison.passage]
        result = {"found": True, "quote": comparison.quote, "page": chosen.get("page"), "source": chosen["source"],
                  "differences": [d.model_dump() for d in comparison.differences]}
    _cache[key] = result
    return result
