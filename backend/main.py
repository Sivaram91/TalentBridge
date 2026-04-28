"""Entry point — starts FastAPI + APScheduler + pystray."""
import threading
import uvicorn
from .db import init_db
from .models import ensure_settings_table
from .config import load_partners
from .scheduler import start_scheduler

PORT = 7070


def run_server():
    from .api import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main():
    init_db()
    ensure_settings_table()
    load_partners()

    # Start scheduler in background thread
    start_scheduler()

    # Start pystray in background thread (imports deferred — optional dependency)
    try:
        from .tray import run_tray
        tray_thread = threading.Thread(target=run_tray, daemon=True)
        tray_thread.start()
    except Exception:
        pass  # tray is optional; headless environments skip it

    # FastAPI blocks the main thread
    run_server()


if __name__ == "__main__":
    main()
