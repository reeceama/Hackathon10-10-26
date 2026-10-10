"""HTTPS server for the Word add-in.

Word only loads add-ins over HTTPS and blocks calls from them to plain-HTTP servers,
so this serves the task pane over HTTPS and passes /api/... through to the backend
(http://localhost:8000). The add-in and the browser extension share one backend.

    1. Backend running:   cd server && uvicorn main:app
    2. Certificates:      npx office-addin-dev-certs install   (once)
    3. This server:       python word-addin/server.py
"""

from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

BACKEND = "http://localhost:8000"
CERTS = Path.home() / ".office-addin-dev-certs"

app = FastAPI()


@app.middleware("http")
async def no_cache(request: Request, call_next):

    """
    Stop Word caching the add-in's files, so changes show up on the next reload.
    """

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.api_route("/api/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):

    """
    Forward a request to the backend and return its response unchanged.
    """

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.request(
            request.method,
            f"{BACKEND}/{path}",
            content=await request.body(),
            headers={"Content-Type": request.headers.get("content-type", "application/json"), "X-Referee": "1"},
        )
    return Response(response.content, response.status_code, media_type=response.headers.get("content-type"))


app.mount("/", StaticFiles(directory=Path(__file__).with_name("static"), html=True))


if __name__ == "__main__":

    uvicorn.run(
        app,
        host="localhost",
        port=3000,
        ssl_keyfile=CERTS / "localhost.key",
        ssl_certfile=CERTS / "localhost.crt",
    )
