"""Learns which markers this student finds useful, from what they do anyway.

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

EVENTS_FILE = Path(__file__).with_name("feedback.json")
MIN_EVENTS = 4
SHOW_MIN = 0.5  # hide a marker when its predicted chance of being useful is below this

# event -> (useful?, weight). Explicit actions count fully; implicit ones are noisier.
EVENTS = {
    "opened_source": (1, 1.0),  # clicked through to the source
    "edited_after": (1, 0.5),   # rewrote the sentence after a warning: the warning helped
    "dismissed": (0, 1.0),      # clicked the marker's x
    "ignored": (0, 0.3),        # carried on without interacting
}

_events = []
_model = None


def features(marker):
    """What the model learns from: verifier confidence, search similarity, and marker type."""
    return [
        float(marker.get("confidence") or 0),
        float(marker.get("score") or 0),
        1.0 if marker.get("label") == "contradicts" else 0.0,
    ]


def _fit():
    """Refit on every event so far, or fall back to showing everything if there's too little."""
    global _model
    useful = [EVENTS[e["event"]][0] for e in _events]
    if len(_events) < MIN_EVENTS or len(set(useful)) < 2:
        _model = None
        return
    X = np.array([features(e) for e in _events])
    weights = [EVENTS[e["event"]][1] for e in _events]
    _model = make_pipeline(StandardScaler(), LogisticRegression())
    _model.fit(X, useful, logisticregression__sample_weight=weights)


def record(event):
    """Store one behaviour event and update the model. Returns False for unknown events."""
    if event.get("event") not in EVENTS:
        return False
    _events.append(event)
    EVENTS_FILE.write_text(json.dumps(_events))
    _fit()
    return True


def usefulness(marker):
    """Predicted chance this student finds the marker useful, or None during cold start."""
    if _model is None:
        return None
    return float(_model.predict_proba([features(marker)])[0][1])


def should_show(marker):
    p = usefulness(marker)
    return p is None or p >= SHOW_MIN


def summary():
    """How much the model has learned - handy for the demo and debugging."""
    counts = {name: sum(e["event"] == name for e in _events) for name in EVENTS}
    if _model is None:
        return {"events": len(_events), "counts": counts, "learning": False}
    weights = _model.named_steps["logisticregression"].coef_[0]
    return {
        "events": len(_events),
        "counts": counts,
        "learning": True,
        "weights": dict(zip(["confidence", "score", "contradicts"], weights.round(2).tolist())),
    }


def reset():
    _events.clear()
    EVENTS_FILE.unlink(missing_ok=True)
    _fit()


if EVENTS_FILE.exists():
    _events.extend(json.loads(EVENTS_FILE.read_text()))
    _fit()


if __name__ == "__main__":
    # Simulated session: the student opens sources for confident markers and
    # dismisses or ignores weak ones. Weak markers should then be hidden.
    EVENTS_FILE = Path("/tmp/feedback_test.json")
    reset()
    strong = {"confidence": 0.93, "score": 0.86, "label": "supports"}
    weak = {"confidence": 0.65, "score": 0.58, "label": "supports"}
    print("Before any feedback, weak marker shown:", should_show(weak))
    for event, marker in [
        ("opened_source", strong),
        ("dismissed", weak),
        ("opened_source", {**strong, "confidence": 0.9}),
        ("ignored", {**weak, "confidence": 0.68}),
        ("dismissed", {**weak, "score": 0.6}),
    ]:
        record({"event": event, **marker})
        print(f"after {event:<13} weak p={usefulness(weak)}  strong p={usefulness(strong)}")
    print("\nWeak marker shown:", should_show(weak), "| strong marker shown:", should_show(strong))
    print(summary())
    reset()
