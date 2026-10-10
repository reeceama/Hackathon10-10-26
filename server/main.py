import time
from datetime import date
from pathlib import Path

import trafilatura
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
 
from extract import extract_page
from store import add_page, clear, search
from verify import verify
from feedback import FeedbackModel
 
# Minimum similarity score before a passage is sent to Claude at all.
# Set this from the scores load_demo.py prints for your real demo sources.
MIN_SCORE = 0.5

feedback = FeedbackModel(Path(__file__).with_name("feedback.json"))


class WritingSession:

    """
    Whether someone is writing right now. The Word add-in pings while its panel is open;
    in automatic mode the browser extension captures reading while this is active.
    """

    ACTIVE_FOR = 5 * 60  # seconds after the last ping

    def __init__(self):

        self.last_ping = 0.0

    def ping(self):

        self.last_ping = time.time()

    def active(self):

        return time.time() - self.last_ping < self.ACTIVE_FOR


writing = WritingSession()
 
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
 
 
class CaptureRequest(BaseModel):
    url: str
    html: str
 
 
class CheckRequest(BaseModel):
    sentence: str
 
 
class CaptureUrlRequest(BaseModel):
    url: str


class FeedbackRequest(BaseModel):
    event: str            # "opened_source" | "edited_after" | "dismissed" | "ignored"
    sentence: str = ""
    url: str = ""
    label: str = ""
    confidence: float = 0
    score: float = 0
 
 
@app.get("/")
def health():
    return {"status": "Referee server running"}
 
 
@app.post("/capture")
def capture(req: CaptureRequest):
    try:
        _, metadata, passages = extract_page(req.html, url=req.url)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    metadata["captured_at"] = date.today().isoformat()  # APA access date
    added = add_page(metadata, passages)
    if added == 0:
        return {"ok": True, "passages": 0, "already_captured": True}
    return {"ok": True, "passages": added}
 
 
@app.post("/check")
def check(req: CheckRequest):
    sentence = req.sentence.strip()
    if len(sentence.split()) < 5:          # too short to carry a real claim
        return {"match": False}
 
    results = search(sentence, k=5)  # 3 missed the best passage in testing
    candidates = [r for r in results if r["score"] >= MIN_SCORE]
    if not candidates:
        return {"match": False}
 
    verdict = verify(sentence, candidates)
    if verdict is None:
        return {"match": False}
    if not feedback.should_show(verdict):  # this person keeps rejecting markers like this
        return {"match": False}
    # verdict includes "label": "supports" or "contradicts" - the editor must handle both
    return {"match": True, **verdict}
 
 
@app.post("/feedback")
def record_feedback(req: FeedbackRequest):
    return {"ok": feedback.record(req.model_dump())}


@app.get("/feedback")
def feedback_summary():
    return feedback.summary()


@app.post("/feedback/reset")
def reset_feedback():
    feedback.reset()
    return {"ok": True}


@app.post("/writing")
def writing_ping():
    writing.ping()
    return {"ok": True}


@app.get("/writing")
def writing_status():
    return {"active": writing.active()}


@app.post("/clear")
def clear_store():
    clear()
    return {"ok": True}
 
 
# --- Debug only: capture by URL so you can test from /docs without the extension ---
@app.post("/debug/capture-url")
def capture_url(req: CaptureUrlRequest):
    html = trafilatura.fetch_url(req.url)
    if html is None:
        return {"ok": False, "reason": "Could not fetch that URL."}
    return capture(CaptureRequest(url=req.url, html=html))