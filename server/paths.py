"""Where Referee keeps its data: your reading, claims, projects, feedback and saved verdicts.

~/Library/Application Support/Referee on macOS, %LOCALAPPDATA%/Referee on Windows,
~/.local/share/referee elsewhere, or the folder in REFEREE_DATA if set (the tests use that).
Kept out of the code's folder, so the code can live inside an app.
"""

import os
import shutil
import sys
from pathlib import Path

LEGACY = ["store.json", "store.npy", "claims.json", "reading.json", "feedback.json", "verdicts.json"]


def data_folder() -> Path:

    if os.environ.get("REFEREE_DATA"):
        folder = Path(os.environ["REFEREE_DATA"])
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Referee"
    elif sys.platform == "win32":
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Referee"
    else:
        folder = Path.home() / ".local" / "share" / "referee"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


DATA = data_folder()

# Data saved next to the code by earlier versions moves here once, so nothing is lost.
if not os.environ.get("REFEREE_DATA"):
    for name in LEGACY:
        old, new = Path(__file__).with_name(name), DATA / name
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))


def data(name: str) -> Path:

    return DATA / name
