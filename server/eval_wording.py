"""Calibrate the too-close-to-source check: word-run length (n), stock-phrase threshold and cut-off.

Each passage (from the Wikipedia article on the Mediterranean diet) has four sentences:
    copy        - copied without quotation marks            -> should flag
    light_edit  - copied with a word or two swapped          -> should flag
    paraphrase  - same meaning, the person's own wording    -> should not flag
    own_words   - same topic, not based on this passage      -> should not flag

Stock phrases (runs recurring across different sentences of the research) are ignored.
The research is the whole captured article from store.json, so run the live test first.

For each setting, the check separates the two groups perfectly if every should-flag sentence
scores above every should-not-flag one. The gap between them is the margin; the cut-off
goes in the middle of it.

    python eval_wording.py
"""

import json
from pathlib import Path

import pandas as pd

from verify import copied_share, stock_phrases

RESEARCH = Path("store.json")

PASSAGES = {
    "foods": (
        "It emphasizes plant-based foods, particularly unprocessed cereals, legumes, vegetables, "
        "and fruits; moderate consumption of fish and dairy products (mostly cheese and yogurt); "
        "and low amounts of red meat, refined grains, and sugar."
    ),
    "heart": (
        "A 2017 review provided evidence that the Mediterranean diet lowers the risk of heart "
        "disease and early death; it may also help with weight loss in obese people."
    ),
    "heart_full": (
        "The Mediterranean diet is associated with a reduction in all-cause mortality in observational "
        "studies. A 2017 review provided evidence that the Mediterranean diet lowers the risk of heart "
        "disease and early death; it may also help with weight loss in obese people."
    ),
    "olive_oil": (
        "A 2014 meta-analysis concluded that an elevated consumption of olive oil is associated "
        "with reduced risk of all-cause mortality, cardiovascular events and stroke, while "
        "monounsaturated fatty acids of mixed animal and plant origin showed no significant effects."
    ),
    "diabetes": (
        "The American Diabetes Association and a 2019 review indicated that the Mediterranean diet "
        "is a healthy dietary pattern that may reduce the risk of diabetes."
    ),
    "alzheimers": (
        "According to a 2013 systematic review, greater adherence to a Mediterranean diet is "
        "correlated with a lower risk of Alzheimer's disease and slower cognitive decline."
    ),
}

SENTENCES = [
    ("foods", "copy", "The diet emphasizes plant-based foods, particularly unprocessed cereals, legumes, vegetables, and fruits."),
    ("foods", "light_edit", "It focuses on plant-based foods, especially unprocessed cereals, legumes, vegetables and fruit, with moderate consumption of fish and dairy products."),
    ("foods", "paraphrase", "Most of the diet comes from plants such as whole grains, beans, vegetables and fruit, with fish and dairy eaten in moderation."),
    ("foods", "own_words", "The Mediterranean diet places plants at the centre of every meal and keeps red meat to a minimum."),
    ("heart", "copy", "A 2017 review provided evidence that the Mediterranean diet lowers the risk of heart disease and early death."),
    ("heart", "light_edit", "A 2017 review gave evidence that the Mediterranean diet reduces the risk of heart disease and early death."),
    ("heart", "paraphrase", "According to a review published in 2017, eating this way cuts the chance of dying young or developing heart problems."),
    ("heart", "own_words", "The Mediterranean diet is associated with a lower risk of cardiovascular disease and death."),
    # The false alarm seen in the live test: own words, but sharing the article's stock phrasing.
    ("heart_full", "own_words", "The Mediterranean diet is associated with a lower risk of cardiovascular disease and death."),
    ("olive_oil", "copy", "An elevated consumption of olive oil is associated with reduced risk of all-cause mortality, cardiovascular events and stroke."),
    ("olive_oil", "light_edit", "A 2014 meta-analysis found that a high consumption of olive oil is associated with reduced risk of all-cause mortality, cardiovascular events and stroke."),
    ("olive_oil", "paraphrase", "Pooled studies from 2014 suggest people who use more olive oil are less likely to die early, have a stroke or suffer heart attacks."),
    ("olive_oil", "own_words", "Olive oil is thought to be one of the main reasons the Mediterranean diet is associated with better heart health."),
    ("diabetes", "copy", "The Mediterranean diet is a healthy dietary pattern that may reduce the risk of diabetes."),
    ("diabetes", "light_edit", "The American Diabetes Association indicated that the Mediterranean diet is a healthy eating pattern that may lower the risk of diabetes."),
    ("diabetes", "paraphrase", "Diabetes experts consider this way of eating a sensible choice for people hoping to avoid developing the condition."),
    ("diabetes", "own_words", "Following the Mediterranean diet may reduce the risk of type 2 diabetes."),
    ("alzheimers", "copy", "Greater adherence to a Mediterranean diet is correlated with a lower risk of Alzheimer's disease and slower cognitive decline."),
    ("alzheimers", "light_edit", "According to a 2013 systematic review, closer adherence to a Mediterranean diet is linked with a lower risk of Alzheimer's disease and slower cognitive decline."),
    ("alzheimers", "paraphrase", "People who stick closely to the diet seem less likely to develop Alzheimer's, and their thinking skills decline more slowly."),
    ("alzheimers", "own_words", "There is some evidence that the Mediterranean diet may protect the brain as people age."),
]

SHOULD_FLAG = {"copy", "light_edit"}


def calibrate():
    if RESEARCH.exists():
        research = [p["text"] for p in json.loads(RESEARCH.read_text())]
    else:
        print(f"{RESEARCH} not found - using only the calibration passages as the research.")
        research = list(PASSAGES.values())

    df = pd.DataFrame(SENTENCES, columns=["passage", "kind", "sentence"])
    df["should_flag"] = df["kind"].isin(SHOULD_FLAG)

    rows = []
    for n in (3, 4, 5, 6):
        for stock_min in (2, 3, 4, None):  # None = no stock filtering
            stock = stock_phrases(research, n, stock_min) if stock_min else frozenset()
            column = f"n{n}_s{stock_min or '-'}"
            df[column] = [
                copied_share(s, PASSAGES[p], n, stock) for p, s in zip(df["passage"], df["sentence"])
            ]
            lowest_flag = df.loc[df["should_flag"], column].min()
            highest_clean = df.loc[~df["should_flag"], column].max()
            rows.append({
                "n": n,
                "stock_min": stock_min or "off",
                "highest_should_not_flag": highest_clean,
                "lowest_should_flag": lowest_flag,
                "margin": lowest_flag - highest_clean,
                "cut_off": (lowest_flag + highest_clean) / 2,
            })

    summary = pd.DataFrame(rows).sort_values("margin", ascending=False)
    print("Separation by setting (perfect when margin > 0), best first:")
    print(summary.round(3).to_string(index=False))

    best = summary.iloc[0]
    column = f"n{int(best.n)}_s{best.stock_min if best.stock_min != 'off' else '-'}"
    print(f"\nScores with the best setting ({column}):")
    print(df[["passage", "kind", column]].round(2).to_string(index=False))
    print(
        f"\nBest: {int(best.n)}-word runs, stock phrases = runs in >= {best.stock_min} sentences, "
        f"cut-off {best.cut_off:.2f} (margin {best.margin:.2f}: should-not-flag max "
        f"{best.highest_should_not_flag:.2f}, should-flag min {best.lowest_should_flag:.2f})"
    )


if __name__ == "__main__":
    calibrate()
