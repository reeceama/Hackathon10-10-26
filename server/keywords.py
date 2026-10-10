"""Keyword search (BM25) over stored passages.

Meaning-based search can blur exact terms, names and figures ("13%", "2017", "Cochrane"),
so search combines it with this, which rewards passages sharing the sentence's actual words.
"""

import math
import re
from collections import Counter
from typing import Dict, List

TOKEN = re.compile(r"[a-z0-9%]+(?:\.[0-9]+)?")
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the
this to was were which with than then there these those not no but can may also""".split())


def tokens(text: str) -> List[str]:

    """
    Lower-case words and numbers, without common words.
    """

    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


class KeywordIndex:

    """
    BM25 scores for a growing list of passages.
    """

    K1 = 1.5   # how quickly repeated terms stop adding to the score
    B = 0.75   # how much long passages are penalised

    def __init__(self):

        self.counts: List[Counter] = []
        self.lengths: List[int] = []
        self.document_frequency: Counter = Counter()

    def add(self, texts: List[str]) -> None:

        for text in texts:
            terms = Counter(tokens(text))
            self.counts.append(terms)
            self.lengths.append(sum(terms.values()))
            self.document_frequency.update(terms.keys())

    def clear(self) -> None:

        self.__init__()

    def scores(self, query: str) -> Dict[int, float]:

        """
        BM25 score for every passage sharing at least one term with the query.
        """

        n = len(self.counts)
        if n == 0:
            return {}
        average = sum(self.lengths) / n
        results: Dict[int, float] = {}
        for term in set(tokens(query)):
            df = self.document_frequency.get(term)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, counts in enumerate(self.counts):
                tf = counts.get(term)
                if tf:
                    norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * self.lengths[i] / average))
                    results[i] = results.get(i, 0.0) + idf * norm
        return results
