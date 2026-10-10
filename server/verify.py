from typing import Literal, Optional

import anthropic
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

MODEL = "claude-haiku-5-5"
THRESHOLD = 0.6  # chosen from the SciFact evaluation: precision 0.95, recall 0.77

SYSTEM_PROMPT = """You check whether a sentence from a student's essay is backed by sources they have read.

You will be given one sentence and one or more numbered passages. Decide whether any passage supports or contradicts the specific claim in the sentence.

Labels:
- "supports": the passage directly backs this exact claim, including its strength and scope (e.g. "strongly", "always", "most").
- "contradicts": the passage directly states something that goes against the claim, including evidence that the effect is much weaker or absent.
- "neutral": anything else. Being about the same topic is NOT support. Partial or indirect relevance is neutral.

Rules:
- Pick the single best passage, or none if all are neutral.
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
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=Verdict,
    )
    return response.parsed_output


def verify(sentence, candidates):
    """Check a sentence against candidate passages.

    candidates: the top matches from store.search - [{"text", "source", "score"}, ...].
    Returns {"source", "passage", "quote", "confidence", "label", "score"} or None.
    """
    if not candidates:
        return None

    passages = "\n\n".join(f"Passage {i}:\n{c['text']}" for i, c in enumerate(candidates, start=1))
    user = f"Sentence:\n{sentence}\n\n{passages}"

    try:
        result = call_llm(SYSTEM_PROMPT, user)
    except anthropic.APIError:
        return None
    if result is None:
        return None

    label = result.label
    confidence = result.confidence
    index = result.passage
    if label not in ("supports", "contradicts") or confidence < THRESHOLD:
        return None
    if not isinstance(index, int) or not 1 <= index <= len(candidates):
        return None

    chosen = candidates[index - 1]
    quote = result.quote
    if quote not in chosen["text"]:
        return None  # never show a quote that isn't really in the source

    return {
        "source": chosen["source"],
        "passage": chosen["text"],
        "quote": quote,
        "confidence": confidence,
        "label": label,
        "score": chosen.get("score"),
    }


if __name__ == "__main__":
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
