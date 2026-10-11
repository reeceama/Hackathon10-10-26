import threading
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
from video import extract_video
from store import add_page, clear, expired, forget, keep, move, rename_project, search, sources
from reading import ReadingSettings
from verify import verify
from claims import needs_source
from feedback import FeedbackModel
from claim_log import ClaimLog
 
# Minimum similarity score before a passage is sent to Claude at all.
# Set this from the scores load_demo.py prints for your real demo sources.
MIN_SCORE = 0.5
CLOSEST_SCORE = 0.3  # loosely related reading worth suggesting for an unsupported claim

feedback = FeedbackModel(Path(__file__).with_name("feedback.json"))
claim_log = ClaimLog(Path(__file__).with_name("claims.json"))
reading = ReadingSettings(Path(__file__).with_name("reading.json"))


def forget_expired_reading():
    # Temporary reading (not saved for later, not cited) is forgotten after keep_minutes.
    while True:
        for url in expired(time.time() - reading.keep_minutes * 60):
            claim_log.forget(url)
            forget(url)
        time.sleep(60)


threading.Thread(target=forget_expired_reading, daemon=True).start()


class WritingSession:

    """
    Whether someone is writing right now. The Word add-in pings while its panel is open;
    in automatic mode the browser extension captures reading while this is active.
    """

    ACTIVE_FOR = 5 * 60  # seconds after the last ping

    HELPER_FOR = 2 * 60  # the Word helper sends a heartbeat every 30 seconds while Word is open

    def __init__(self):

        self.last_ping = 0.0
        self.last_helper = 0.0

    def ping(self):

        self.last_ping = time.time()

    def active(self):

        return time.time() - self.last_ping < self.ACTIVE_FOR

    def helper_running(self):

        return time.time() - self.last_helper < self.HELPER_FOR


writing = WritingSession()


class FocusMode:

    """
    Research mode switched on from outside the browser, e.g. by a macOS Focus through a
    Shortcuts automation. While it is on, the extension captures reading.
    """

    def __init__(self):

        self.on = False


focus = FocusMode()
 
app = FastAPI()

# Only Referee's own apps may call this server: the browser extension and the Word add-in.
# Any other website a person visits is refused, so it can't spend their API
# credit, wipe their reading or see what they've captured.
REFEREE_ORIGINS = r"^(chrome-extension://[a-p]{32}|https://localhost:3000)$"
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
    project: str = ""  # reading is kept per project; empty means any
 
 
class CheckRequest(BaseModel):
    sentence: str
    project: str = ""  # only check against this project's reading
 
 
class CapturePdfRequest(BaseModel):
    url: str
    project: str = ""
    title: str = ""
    data: str  # the PDF file, base64-encoded


class CaptureVideoRequest(BaseModel):
    url: str
    project: str = ""


class FocusRequest(BaseModel):
    on: bool


class KeepRequest(BaseModel):
    url: str
    project: str = ""


class SettingsRequest(BaseModel):
    project: str | None = None
    projects: list[str] | None = None
    keep_minutes: int | None = None
    links: dict[str, list[str]] | None = None


class RenameRequest(BaseModel):
    old: str
    new: str = ""  # empty: delete the project (its sources are kept, with no project)


class MoveRequest(BaseModel):
    url: str
    project: str = ""


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
 
 
def stamp(metadata, project):
    metadata["captured_at"] = date.today().isoformat()  # APA access date
    metadata["captured_ts"] = time.time()                # for expiring temporary reading
    metadata["project"] = project or reading.project or None
    metadata["kept"] = False                             # temporary until saved or cited


@app.post("/capture")
def capture(req: CaptureRequest):
    try:
        _, metadata, passages = extract_page(req.html, url=req.url)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    stamp(metadata, req.project)
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
    stamp(metadata, req.project)
    added = add_page(metadata, [text for text, _ in passages], pages=[page for _, page in passages])
    if added == 0:
        return {"ok": True, "passages": 0, "already_captured": True}
    return {"ok": True, "passages": added}


@app.post("/capture-video")
def capture_video(req: CaptureVideoRequest):
    try:
        metadata, passages = extract_video(req.url)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    stamp(metadata, req.project)
    added = add_page(metadata, [text for text, _ in passages], times=[time for _, time in passages])
    if added == 0:
        return {"ok": True, "passages": 0, "already_captured": True}
    return {"ok": True, "passages": added}


def closest_sources(results, limit=3):
    seen, closest = set(), []
    for r in results:
        url = r["source"].get("url")
        if url in seen or r["score"] < CLOSEST_SCORE:
            continue
        seen.add(url)
        closest.append({"title": r["source"].get("title"), "url": url, "page": r.get("page"), "time": r.get("time")})
    return closest[:limit]


@app.post("/check")
def check(req: CheckRequest):
    sentence = req.sentence.strip()
    if len(sentence.split()) < 5:          # too short to carry a real claim
        return {"match": False}
 
    project = req.project or reading.project or None
    results = search(sentence, k=5, projects=reading.allowed(project))  # 3 missed the best passage in testing

    # No supporting reading: say whether the sentence reads like a claim that needs one, and
    # which sources already read come closest, as places to look. Nothing is written for them.
    unsupported = {"match": False, "needs_source": needs_source(sentence), "closest": closest_sources(results)}
    candidates = [r for r in results if r["score"] >= MIN_SCORE]
    if not candidates:
        return unsupported
 
    verdict = verify(sentence, candidates)
    if verdict is None:
        return unsupported
    if not feedback.should_show(verdict):  # this person keeps rejecting markers like this
        return {"match": False}
    claim_log.record(sentence, verdict, project)  # for the library and proof of work
    if verdict.get("label") == "supports" and verdict.get("source", {}).get("url"):
        keep(verdict["source"]["url"])  # cited sources are kept automatically
    # verdict includes "label": "supports" or "contradicts" - Word handles both
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
    return {"active": writing.active(), "focus": focus.on, "helper": writing.helper_running()}


@app.post("/helper")
def helper_heartbeat():
    # The background Word helper is running, so the Word add-in leaves documents to it.
    writing.last_helper = time.time()
    return {"ok": True}


@app.post("/focus")
def set_focus(req: FocusRequest):
    focus.on = req.on
    return {"ok": True, "focus": focus.on}


@app.get("/sources")
def list_sources():
    return sources()


@app.delete("/sources")
def forget_source(url: str):
    claim_log.forget(url)
    return {"ok": True, "removed": forget(url)}


@app.post("/sources/forget-temporary")
def forget_temporary():
    # Everything not saved for later or cited, now rather than when it expires.
    urls = expired(time.time() + 1)
    for url in urls:
        claim_log.forget(url)
        forget(url)
    return {"ok": True, "forgotten": len(urls)}


@app.post("/sources/keep")
def keep_source(req: KeepRequest):
    # "Save for later": kept permanently, in the given or current project.
    return {"ok": keep(req.url, req.project or reading.project or None)}


@app.post("/sources/move")
def move_source(req: MoveRequest):
    return {"ok": move(req.url, req.project or None)}


@app.post("/projects/rename")
def rename_project_route(req: RenameRequest):
    new = req.new.strip()
    rename_project(req.old, new or None)
    claim_log.rename_project(req.old, new or None)
    return reading.rename(req.old, new)


@app.get("/settings")
def get_settings():
    return reading.as_dict()


@app.post("/settings")
def set_settings(req: SettingsRequest):
    return reading.update(req.model_dump(exclude_none=True))


@app.get("/claims")
def list_claims(project: str = ""):
    return claim_log.claims(project or None)


@app.post("/clear")
def clear_store():
    clear()
    claim_log.clear()
    return {"ok": True}
 
 
# --- Debug only: capture by URL so you can test from /docs without the extension ---
@app.post("/debug/capture-url")
def capture_url(req: CaptureUrlRequest):
    html = trafilatura.fetch_url(req.url)
    if html is None:
        return {"ok": False, "reason": "Could not fetch that URL."}
    return capture(CaptureRequest(url=req.url, html=html))