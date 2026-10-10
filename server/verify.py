import re
import sys
from collections import Counter
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(timeout=10.0)  # never leave the editor waiting

MODEL = "claude-haiku-5-5"
THRESHOLD = 0.6  # chosen from the SciFact evaluation: precision 0.91 (95% CI 0.81-0.96), recall 0.76
# Calibrated in eval_wording.py (margin 0.32 between copying and own words on 21 sentences):
NGRAM = 3  # length of the word runs compared when checking for copying
STOCK_MIN = 4  # a run in at least this many different sentences of the research is stock phrasing
TOO_CLOSE = 0.3  # share of the sentence's distinctive runs found in the passage
MISQUOTE_MIN = 0.3  # a non-matching quotation is only a misquote if this much of it matches the reading
MIN_QUOTE_WORDS = 4  # shortest supporting quote accepted from the verifier

SYSTEM_PROMPT = """You check whether a sentence someone has written is backed by sources they have read.

You will be given one sentence and one or more numbered passages. Decide whether any passage supports or contradicts the specific claim in the sentence.

Labels:
- "supports": the passage directly backs this exact claim, including its strength and scope (e.g. "strongly", "always", "most").
- "contradicts": the passage directly states something that goes against the claim, including evidence that the effect is much weaker or absent.
- "neutral": anything else. Being about the same topic is NOT support. Partial or indirect relevance is neutral.

Rules:
- Pick the single best passage, or none if all are neutral.
- If passages disagree, judge by the one that addresses the claim most directly. A claim about the
  general case is not contradicted by an exception or a qualification (e.g. "not in every country").
- "quote" must be copied word for word from the chosen passage: the shortest span that justifies your label.
- "passage" is the chosen passage's number, or null if none.
- "confidence" is how sure you are of the label, from 0 to 1."""


class Verdict(BaseModel):
    passage: Optional[int]
    label: Literal["supports", "contradicts", "neutral"]
    confidence: float
    quote: str


def call_llm(system, user):
    """Ask Claude for a verdict. Structured outputs guarantee the reply matches Verdict."""
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1500,  # the model thinks before answering; replies used up to ~700 tokens in testing
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=Verdict,
    )
    return response.parsed_output


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
GAPS = re.compile(r"\.\.\.|…|\[[^\]]*\]")  # ellipses and [editorial insertions]


def normalise(text):
    """Lower case, straight quotes and apostrophes, single spaces, no edge punctuation."""
    text = text.lower().translate(str.maketrans("‘’“”", "''\"\""))
    return " ".join(text.split()).strip(" .,;:!?")


def split_quotes(sentence):
    """Return (quoted strings, the sentence with them removed)."""
    quotes = [a or b for a, b in QUOTED.findall(sentence)]
    return quotes, QUOTED.sub(" ", sentence)


def quote_in_source(quote, source):
    """True if a quotation appears word for word in the source.

    Ellipses and [square-bracketed] insertions mark gaps: each piece between
    them must appear in the source, in order.
    """
    source = normalise(source)
    position = 0
    for piece in GAPS.split(quote):
        piece = normalise(piece)
        if not piece:
            continue
        found = source.find(piece, position)
        if found == -1:
            return False
        position = found + len(piece)
    return True


def ngrams(text, n=None):
    """The set of n-word runs in the text."""
    n = n or NGRAM
    words = re.findall(r"[a-z0-9']+", normalise(text))
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def stock_phrases(texts, n=None, min_count=None):
    """Word runs that recur across different sentences of the research.

    A run like "the mediterranean diet is associated" that appears all over the
    reading is the topic's standard wording, not copying from one passage.
    Counted over distinct sentences because stored passages overlap.
    """
    min_count = min_count or STOCK_MIN
    sentences = {normalise(s) for text in texts for s in SENTENCE_END.split(text)}
    counts = Counter(run for s in sentences for run in ngrams(s, n))
    return {run for run, count in counts.items() if count >= min_count}


def research_passages():
    """Every passage captured so far, if the server has loaded the store (empty in tests)."""
    store = sys.modules.get("store")
    return [p["text"] for p in getattr(store, "_passages", [])]


def copied_share(text, source, n=None, stock=frozenset()):
    """Share of the text's distinctive n-word runs that also appear in the source (0 to 1)."""
    own = ngrams(text, n) - stock
    if not own:
        return 0.0
    return len(own & ngrams(source, n)) / len(own)


def is_misquote(quote, source):
    """The quotation isn't in the source word for word, yet clearly comes from it.

    A quotation that resembles nothing in the source probably comes from reading that
    wasn't captured, so it isn't flagged.
    """
    return not quote_in_source(quote, source) and copied_share(quote, source) >= MISQUOTE_MIN


def check_wording(sentence, passage, all_text=None, stock=frozenset()):
    """Quotes must match the source exactly; everything else must not copy the passage too closely.

    Quotations are checked against all_text (every candidate passage) when given,
    since a quotation may come from a neighbouring passage. Stock phrases are
    ignored when measuring copying.
    """
    quotes, unquoted = split_quotes(sentence)
    return {
        "misquote": any(is_misquote(q, all_text or passage) for q in quotes),
        "too_close": copied_share(unquoted, passage, stock=stock) >= TOO_CLOSE,
    }


def misquote_marker(sentence, candidates):
    """A marker for a misquotation, even when the claim itself wasn't verified.

    The quote field holds the source sentence closest to what the person quoted,
    so the frontend can show what the source actually says.
    """
    all_text = " ".join(c["text"] for c in candidates)
    for quote in split_quotes(sentence)[0]:
        if not is_misquote(quote, all_text):
            continue
        best = max(candidates, key=lambda c: copied_share(quote, c["text"]))
        closest = max(SENTENCE_END.split(best["text"]), key=lambda s: copied_share(quote, s))
        return {
            "source": best["source"],
            "passage": best["text"],
            "quote": closest,
            "confidence": 1.0,
            "label": "misquote",
            "score": best.get("score"),
            "misquote": True,
            "too_close": False,
        }
    return None


def verify(sentence, candidates, threshold=THRESHOLD):
    """Check a sentence against candidate passages.

    candidates: the top matches from store.search - [{"text", "source", "score"}, ...].
    Returns {"source", "passage", "quote", "confidence", "label", "score", "misquote", "too_close"}
    or None. label is "supports", "contradicts", or "misquote" (a quotation that doesn't match
    the source, on a claim that couldn't be verified).
    """
    if not candidates:
        return None
    return _verified(sentence, candidates, threshold) or misquote_marker(sentence, candidates)


def _verified(sentence, candidates, threshold):
    """Claude's verdict, if it confidently supports or contradicts the sentence."""
    passages = "\n\n".join(f"Passage {i}:\n{c['text']}" for i, c in enumerate(candidates, start=1))
    user = f"Sentence:\n{sentence}\n\n{passages}"

    try:
        result = call_llm(SYSTEM_PROMPT, user)
    except anthropic.APIError as e:
        print(f"[verify] API error: {e}")  # shows in the uvicorn terminal
        return None
    if result is None:
        return None

    label = result.label
    confidence = result.confidence
    index = result.passage
    if label not in ("supports", "contradicts") or confidence < threshold:
        return None
    if not isinstance(index, int) or not 1 <= index <= len(candidates):
        return None

    chosen = candidates[index - 1]
    quote = result.quote
    # The quote must be real text from the source. An empty or tiny quote would pass a plain
    # "in" check ("" is in every string), so require a few words, and compare normalised text
    # so curly quotes or spacing differences don't reject a genuine quote.
    if len(quote.split()) < MIN_QUOTE_WORDS or normalise(quote) not in normalise(chosen["text"]):
        return None  # never show a quote that isn't really in the source

    return {
        "source": chosen["source"],
        "passage": chosen["text"],
        "quote": quote,
        "confidence": confidence,
        "label": label,
        "score": chosen.get("score"),
        **check_wording(
            sentence,
            chosen["text"],
            all_text=" ".join(c["text"] for c in candidates),
            stock=stock_phrases(research_passages()),
        ),
    }


if __name__ == "__main__":
    source = (
        "A 10-year cohort study found that adults who exercised three times a week "
        "had a 30% lower incidence of cardiovascular disease than those who did not."
    )
    wording_tests = [
        # (sentence, expected misquote, expected too_close)
        ('One study found "a 30% lower incidence of cardiovascular disease" among regular exercisers.', False, False),
        ("One study found “a 30% lower incidence of cardiovascular disease” among regular exercisers.", False, False),
        ('Adults who exercised "three times a week had a 40% lower incidence" of heart disease.', True, False),
        ('Regular exercisers "had a 30% lower incidence of [heart] disease than those who did not."', False, False),
        ('The study "found that adults ... had a 30% lower incidence" of disease.', False, False),
        ("Adults who exercised three times a week had a 30% lower incidence of cardiovascular disease.", False, True),
        ("People who work out regularly are noticeably less likely to develop heart problems.", False, False),
        ('As one author put it, "the evidence base is still developing" in this area.', False, False),
    ]
    print("Wording checks:")
    for sentence, misquote, too_close in wording_tests:
        got = check_wording(sentence, source)
        ok = got == {"misquote": misquote, "too_close": too_close}
        print(f"{'✓' if ok else '✗'} {got} | {sentence}")

    print("\nVerifier:")
    tests = [
        # (sentence, passage, expected label)
        (
            "Regular exercise lowers the risk of heart disease.",
            "A 10-year cohort study found that adults who exercised three times a week had a 30% lower incidence of cardiovascular disease.",
            "supports",
        ),
        (
            "Remote workers report higher job satisfaction than office workers.",
            "In a 2023 survey of 12,000 employees, fully remote staff rated their job satisfaction 7.8 out of 10 on average, compared with 6.9 for those working in the office full time.",
            "supports",
        ),
        (
            "Social media use is strongly linked to depression in teenagers.",
            "A large longitudinal analysis of 17,000 adolescents found only a very small association between social media use and depressive symptoms, comparable in size to the effect of eating potatoes.",
            "contradicts",
        ),
        (
            "Drinking coffee improves long-term memory.",
            "Caffeine is the world's most widely consumed stimulant, and a typical cup of coffee contains around 95mg of it. It increases alertness by blocking adenosine receptors in the brain.",
            "neutral",
        ),
        (
            "The Treaty of Versailles was signed in 1919.",
            "Photosynthesis converts light energy into chemical energy, producing glucose and oxygen from carbon dioxide and water.",
            "neutral",
        ),
    ]

    correct = 0
    for sentence, passage, expected in tests:
        match = verify(sentence, [{"text": passage, "source": {"url": "test", "title": "test"}}])
        actual = match["label"] if match else "neutral"
        correct += actual == expected
        mark = "✓" if actual == expected else "✗"
        confidence = f"{match['confidence']:.2f}" if match else "-"
        print(f"{mark} expected={expected:<11} actual={actual:<11} conf={confidence} | {sentence}")
    print(f"\n{correct}/{len(tests)} correct")
