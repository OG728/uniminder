"""Run UniMinder in its own window, with the server hidden in the background."""

import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# pythonw has no console, so send output to a log file instead of nowhere.
if sys.stdout is None or sys.stderr is None:
    (ROOT / "data").mkdir(exist_ok=True)
    log = open(ROOT / "data" / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log

import uvicorn  # noqa: E402
import webview  # noqa: E402

from app.main import app  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    )
    threading.Thread(target=server.run, daemon=True).start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    webview.create_window(
        "UniMinder",
        f"http://127.0.0.1:{port}",
        width=1320,
        height=880,
        min_size=(900, 600),
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import ctypes
        import traceback

        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(
            None, "UniMinder couldn't start. Details are in data/app.log.", "UniMinder", 0x10
        )
