"""Passages from YouTube videos: the transcript in chunks, each with the time it starts.

The transcript is the video's own captions, fetched with youtube-transcript-api. The title
and channel come from YouTube's public oEmbed endpoint. Neither needs an API key.
"""

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from youtube_transcript_api import YouTubeTranscriptApi

CHUNK_SECONDS = 20  # shorter chunks match spoken claims better; 30 missed one of four tests
LANGUAGES = ["en", "en-GB", "en-US"]


def video_id(url: str) -> Optional[str]:

    """
    The 11-character video ID from a watch, short or youtu.be link.
    """

    parts = urlparse(url)
    if parts.hostname and parts.hostname.endswith("youtu.be"):
        return parts.path.lstrip("/")[:11] or None
    if parts.path == "/watch":
        return (parse_qs(parts.query).get("v") or [None])[0]
    match = re.match(r"^/(shorts|embed|live)/([\w-]{11})", parts.path)
    return match.group(2) if match else None


def details(url: str) -> Dict[str, Optional[str]]:

    """
    Title and channel name for a video, or empty values if YouTube doesn't say.
    """

    try:
        data = requests.get(f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json", timeout=10).json()
        return {"title": data.get("title"), "author": data.get("author_name")}
    except (requests.RequestException, ValueError):
        return {"title": None, "author": None}


def extract_video(url: str) -> Tuple[Dict, List[Tuple[str, int]]]:

    """
    Return metadata and a list of (passage, start time in seconds) for a YouTube video.
    """

    vid = video_id(url)
    if not vid:
        raise ValueError("Not a YouTube video link.")
    try:
        transcript = YouTubeTranscriptApi().fetch(vid, languages=LANGUAGES)
    except Exception as error:
        raise ValueError(f"No English transcript available for this video ({type(error).__name__}).")

    passages: List[Tuple[str, int]] = []
    words: List[str] = []
    start = None
    for snippet in transcript:
        if start is None:
            start = snippet.start
        words.append(snippet.text.replace("\n", " ").strip())
        if snippet.start + snippet.duration - start >= CHUNK_SECONDS:
            passages.append((" ".join(words), int(start)))
            words, start = [], None
    if words:
        passages.append((" ".join(words), int(start)))
    if not passages:
        raise ValueError("This video's transcript is empty.")

    info = details(f"https://www.youtube.com/watch?v={vid}")
    metadata = {
        "title": info["title"],
        "author": info["author"],
        "date": None,  # oEmbed doesn't give an upload date
        "site": "YouTube",
        "url": f"https://www.youtube.com/watch?v={vid}",
        "type": "video",
    }
    return metadata, passages
