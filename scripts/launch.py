"""Start the SPHEREx Sky Flip-book and open it in the browser once it is ready.

Used by start.bat. If the tool is already running (for example from an earlier
double-click), it just opens the browser instead of failing on a busy port.
"""
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000/"


def is_up() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/lenses", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def open_page():
    # a fresh address each time, so the browser can't show an old saved copy of the page
    webbrowser.open(f"{URL}?t={int(time.time())}")


def open_when_ready():
    for _ in range(120):  # up to 60 seconds
        if is_up():
            print("\n  Ready! Opening", URL, "in your browser.\n  Keep this window open while you use the tool; close it to stop.\n")
            open_page()
            return
        time.sleep(0.5)
    print("\n  The tool did not start within a minute. Please send a screenshot of this window.\n")


if __name__ == "__main__":
    if is_up():
        print("\n  The tool is already running. Opening", URL, "in your browser.")
        print("  (It keeps running in the other black window. Close that window to stop it.)\n")
        open_page()
        time.sleep(3)
        sys.exit(3)
    print("\n  Starting the SPHEREx Sky Flip-book... (this takes a few seconds)\n")
    sys.path.insert(0, str(ROOT))
    threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, log_level="warning")
