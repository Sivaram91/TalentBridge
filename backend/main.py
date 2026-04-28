"""Entry point — starts FastAPI + APScheduler + pystray."""
import threading
import time
import webbrowser
import uvicorn
from .db import init_db
from .models import ensure_settings_table
from .config import load_partners
from .scheduler import start_scheduler

PORT = 7070


def run_server():
    from .api import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def _open_browser():
    # Give uvicorn a moment to bind before opening the browser
    time.sleep(1.2)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    init_db()
    ensure_settings_table()
    load_partners()

    # Start scheduler in background thread
    start_scheduler()

    # Open browser automatically
    threading.Thread(target=_open_browser, daemon=True).start()

    # Start pystray in background thread (optional — skipped in headless environments)
    try:
        from .tray import run_tray
        threading.Thread(target=run_tray, daemon=True).start()
    except Exception:
        pass

    # FastAPI blocks the main thread
    run_server()


if __name__ == "__main__":
    main()
