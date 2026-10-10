from typing import Optional

import trafilatura
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from extract import extract_page
from store import add_page, clear, search

# Minimum similarity score before a match is considered at all.
# Set this from the scores you recorded in test_store.py.
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
    return {"ok": True, "passages": added}


@app.post("/check")
def check(req: CheckRequest):
    sentence = req.sentence.strip()
    if len(sentence.split()) < 5:          # too short to carry a real claim
        return {"match": False}

    results = search(sentence, k=3)
    if not results or results[0]["score"] < MIN_SCORE:
        return {"match": False}

    # TEMPORARY: return the top search result unverified.
    # verify.py will replace this with Claude's decision + exact quote.
    best = results[0]
    return {
        "match": True,
        "source": best["source"],
        "passage": best["text"],
        "quote": None,
        "score": best["score"],
    }


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