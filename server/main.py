import trafilatura
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
 
from extract import extract_page
from store import add_page, clear, search
from verify import verify
 
# Minimum similarity score before a passage is sent to Claude at all.
# Set this from the scores load_demo.py prints for your real demo sources.
MIN_SCORE = 0.5
 
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
 
 
@app.get("/")
def health():
    return {"status": "Footnote server running"}
 
 
@app.post("/capture")
def capture(req: CaptureRequest):
    try:
        _, metadata, passages = extract_page(req.html, url=req.url)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    added = add_page(metadata, passages)
    if added == 0:
        return {"ok": True, "passages": 0, "already_captured": True}
    return {"ok": True, "passages": added}
 
 
@app.post("/check")
def check(req: CheckRequest):
    sentence = req.sentence.strip()
    if len(sentence.split()) < 5:          # too short to carry a real claim
        return {"match": False}
 
    results = search(sentence, k=3)
    candidates = [r for r in results if r["score"] >= MIN_SCORE]
    if not candidates:
        return {"match": False}
 
    verdict = verify(sentence, candidates)
    if verdict is None:
        return {"match": False}
    # verdict includes "label": "supports" or "contradicts" - the editor must handle both
    return {"match": True, **verdict}
 
 
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