"""Learns which markers this person finds useful, from what they do anyway.

The frontend reports behaviour (opening a source, dismissing a marker, ...). Each event
becomes a labelled example: the marker's features, and whether it was useful. A logistic
regression is refitted on every event and predicts how likely a new marker is to be
useful; markers below SHOW_MIN are hidden.

Until there are MIN_EVENTS events covering both outcomes, every marker the verifier
accepts is shown: the threshold from the SciFact evaluation is the prior, and behaviour
personalises it from there.
"""

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MIN_EVENTS = 4
SHOW_MIN = 0.5  # hide a marker when its predicted chance of being useful is below this

# event -> (useful?, weight). Explicit actions count fully; implicit ones are noisier.
EVENTS = {
    "opened_source": (1, 1.0),  # clicked through to the source
    "edited_after": (1, 0.5),   # rewrote the sentence after a warning: the warning helped
    "dismissed": (0, 1.0),      # clicked the marker's x
    "ignored": (0, 0.3),        # carried on without interacting
}
FEATURES = ["confidence", "score", "contradicts"]


def features(marker):

    """
    What the model learns from: verifier confidence, search similarity, and marker type.
    """

    return [
        float(marker.get("confidence") or 0),
        float(marker.get("score") or 0),
        1.0 if marker.get("label") == "contradicts" else 0.0,
    ]


class FeedbackModel:

    """
    One person's behaviour events and the usefulness model fitted to them.
    """

    def __init__(self, path):

        self.path = Path(path)
        self.events = json.loads(self.path.read_text()) if self.path.exists() else []
        self.model = None
        self._fit()

    def _fit(self):

        """
        Refit on every event so far, or fall back to showing everything if there's too little.
        """

        useful = [EVENTS[e["event"]][0] for e in self.events]
        if len(self.events) < MIN_EVENTS or len(set(useful)) < 2:
            self.model = None
            return
        X = np.array([features(e) for e in self.events])
        weights = [EVENTS[e["event"]][1] for e in self.events]
        self.model = make_pipeline(StandardScaler(), LogisticRegression())
        self.model.fit(X, useful, logisticregression__sample_weight=weights)

    def record(self, event):

        """
        Store one behaviour event and update the model. Returns False for unknown events.
        """

        if event.get("event") not in EVENTS:
            return False
        self.events.append(event)
        self.path.write_text(json.dumps(self.events))
        self._fit()
        return True

    def usefulness(self, marker):

        """
        Predicted chance this person finds the marker useful, or None during cold start.
        """

        if self.model is None:
            return None
        return float(self.model.predict_proba([features(marker)])[0][1])

    def should_show(self, marker):

        p = self.usefulness(marker)
        return p is None or p >= SHOW_MIN

    def summary(self):

        """
        How much the model has learned - handy for the demo and debugging.
        """

        counts = {name: sum(e["event"] == name for e in self.events) for name in EVENTS}
        if self.model is None:
            return {"events": len(self.events), "counts": counts, "learning": False}
        weights = self.model.named_steps["logisticregression"].coef_[0]
        return {
            "events": len(self.events),
            "counts": counts,
            "learning": True,
            "weights": dict(zip(FEATURES, weights.round(2).tolist())),
        }

    def reset(self):

        self.events = []
        self.path.unlink(missing_ok=True)
        self._fit()


if __name__ == "__main__":

    # Simulated session: the person opens sources for confident markers and
    # dismisses or ignores weak ones. Weak markers should then be hidden.
    import tempfile

    feedback = FeedbackModel(Path(tempfile.mkdtemp()) / "feedback.json")
    strong = {"confidence": 0.93, "score": 0.86, "label": "supports"}
    weak = {"confidence": 0.65, "score": 0.58, "label": "supports"}
    print("Before any feedback, weak marker shown:", feedback.should_show(weak))
    for event, marker in [
        ("opened_source", strong),
        ("dismissed", weak),
        ("opened_source", {**strong, "confidence": 0.9}),
        ("ignored", {**weak, "confidence": 0.68}),
        ("dismissed", {**weak, "score": 0.6}),
    ]:
        feedback.record({"event": event, **marker})
        print(f"after {event:<13} weak p={feedback.usefulness(weak)}  strong p={feedback.usefulness(strong)}")
    print("\nWeak marker shown:", feedback.should_show(weak), "| strong marker shown:", feedback.should_show(strong))
    print(feedback.summary())
