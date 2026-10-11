"""Runs Referee's background parts on macOS or Windows: the server, the Word helper and, when
its certificates are installed, the Word add-in's HTTPS server.

Each part is restarted if it stops, and all of them stop when this does. Referee for Mac runs
this; on Windows, scripts/install-windows.bat starts it at login. Logs go to
~/Library/Logs/Referee (macOS) or %LOCALAPPDATA%/Referee/logs (Windows).

Run: python referee.py
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
RESTART_AFTER = 5  # seconds before restarting a part that stopped, so a crash can't spin


def log_folder() -> Path:

    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Referee" / "logs"
    return Path.home() / "Library" / "Logs" / "Referee"


def parts():

    """
    (name, folder, arguments) for each part this computer can run.
    """

    found = [("server", "server", ["-m", "uvicorn", "main:app", "--port", "8000"])]
    if sys.platform in ("darwin", "win32"):
        found.append(("helper", "word-helper", ["helper.py"]))
    if (Path.home() / ".office-addin-dev-certs" / "localhost.crt").exists():
        found.append(("word", "word-addin", ["server.py"]))
    return found


class Launcher:

    def __init__(self):

        self.logs = log_folder()
        self.logs.mkdir(parents=True, exist_ok=True)
        self.running = {}   # name -> Popen
        self.stopping = False

    def start(self, name, folder, arguments):

        log = open(self.logs / f"{name}.log", "a", buffering=1)
        # No console windows on Windows; the parts run quietly in the background.
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.running[name] = subprocess.Popen([sys.executable, *arguments], cwd=REPO / folder,
                                              stdout=log, stderr=subprocess.STDOUT, creationflags=flags)

    def stop(self, *_):

        self.stopping = True
        for process in self.running.values():
            if process.poll() is None:
                process.terminate()
        for process in self.running.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        sys.exit(0)

    def run(self):

        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        everything = parts()
        for part in everything:
            self.start(*part)
        print(f"Referee running: {', '.join(name for name, _, _ in everything)}. Logs: {self.logs}", flush=True)
        stopped_at = {}
        while not self.stopping:
            time.sleep(1)
            for name, folder, arguments in everything:
                if self.running[name].poll() is None:
                    continue
                stopped_at.setdefault(name, time.time())
                if time.time() - stopped_at[name] >= RESTART_AFTER:
                    del stopped_at[name]
                    self.start(name, folder, arguments)


if __name__ == "__main__":
    Launcher().run()
