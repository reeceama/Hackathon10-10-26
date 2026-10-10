import time
from datetime import date
from pathlib import Path

import trafilatura
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
 
import base64

from extract import extract_page
from pdf import extract_pdf
from store import add_page, clear, search
from verify import verify
from claims import needs_source
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

# Only Referee's own apps may call this server: the Chrome extension, the Word add-in and
# Obsidian. Any other website a person visits is refused, so it can't spend their API
# credit, wipe their reading or see what they've captured.
REFEREE_ORIGINS = r"^(chrome-extension://[a-p]{32}|https://localhost:3000|app://obsidian\.md)$"
app.add_middleware(CORSMiddleware, allow_origin_regex=REFEREE_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def referee_only(request: Request, call_next):
    # Browsers only let a page send the X-Referee header to another site if that site allows
    # it, which this one doesn't for ordinary websites. Requests without an Origin come from
    # programs on this computer (curl, scripts); http://localhost:8000 is the /docs page.
    origin = request.headers.get("origin")
    trusted = (
        request.method == "OPTIONS"
        or request.headers.get("x-referee") == "1"
        or origin is None
        or origin == "http://localhost:8000"
    )
    if not trusted:
        return JSONResponse({"error": "Only Referee's own apps can use this server."}, status_code=403)
    return await call_next(request)

 
 
class CaptureRequest(BaseModel):
    url: str
    html: str
 
 
class CheckRequest(BaseModel):
    sentence: str
 
 
class CapturePdfRequest(BaseModel):
    url: str
    title: str = ""
    data: str  # the PDF file, base64-encoded


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
 
 
@app.post("/capture-pdf")
def capture_pdf(req: CapturePdfRequest):
    try:
        metadata, passages = extract_pdf(base64.b64decode(req.data), url=req.url)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    if req.title and not metadata.get("title"):
        metadata["title"] = req.title
    metadata["captured_at"] = date.today().isoformat()  # APA access date
    added = add_page(metadata, [text for text, _ in passages], pages=[page for _, page in passages])
    if added == 0:
        return {"ok": True, "passages": 0, "already_captured": True}
    return {"ok": True, "passages": added}


@app.post("/check")
def check(req: CheckRequest):
    sentence = req.sentence.strip()
    if len(sentence.split()) < 5:          # too short to carry a real claim
        return {"match": False}
 
    # No supporting reading: say whether the sentence reads like a claim that needs one.
    unsupported = {"match": False, "needs_source": needs_source(sentence)}

    results = search(sentence, k=5)  # 3 missed the best passage in testing
    candidates = [r for r in results if r["score"] >= MIN_SCORE]
    if not candidates:
        return unsupported
 
    verdict = verify(sentence, candidates)
    if verdict is None:
        return unsupported
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