"""Entry point — starts FastAPI + APScheduler + pystray."""
import logging
import threading
import time
import webbrowser
import uvicorn
from .db import init_db
from .models import ensure_settings_table
from .config import load_partners
from .scheduler import start_scheduler

logger = logging.getLogger(__name__)
PORT = 7070


class _SuppressCancelledError(logging.Filter):
    """Drop 'Exception in ASGI application' records caused by CancelledError on shutdown."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Exception in ASGI application" in msg:
            return False
        exc = record.exc_info
        if exc and exc[1] is not None:
            import asyncio as _a
            if isinstance(exc[1], (_a.CancelledError, KeyboardInterrupt)):
                return False
        return True


def run_server():
    from .api import app
    # Suppress CancelledError shutdown noise from uvicorn's ASGI error reporter
    for _name in ("uvicorn.error", "uvicorn"):
        logging.getLogger(_name).addFilter(_SuppressCancelledError())
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def _open_browser():
    # Give uvicorn a moment to bind before opening the browser
    time.sleep(1.2)
    webbrowser.open(f"http://localhost:{PORT}")


def _resolve_missing_countries():
    """One-time background pass: fill country for jobs that have location but no country."""
    try:
        from .db import get_conn
        from .geo import resolve_countries_for_jobs
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, location FROM jobs WHERE is_expired=0 AND (country IS NULL OR country='') AND location != '' AND location IS NOT NULL"
            ).fetchall()
        if not rows:
            return
        resolved = resolve_countries_for_jobs([(r["id"], r["location"]) for r in rows])
        with get_conn() as conn:
            for jid, country in resolved:
                if country:
                    conn.execute("UPDATE jobs SET country=? WHERE id=?", (country, jid))
    except Exception as e:
        logger.error("Country resolution pass failed: %s", e, exc_info=True)


def main():
    init_db()
    ensure_settings_table()
    load_partners()

    # Resolve countries for existing jobs in background
    threading.Thread(target=_resolve_missing_countries, daemon=True).start()

    # Start scheduler in background thread
    start_scheduler()

    # Open browser automatically
    threading.Thread(target=_open_browser, daemon=True).start()

    # Start pystray in background thread (optional — skipped in headless environments)
    try:
        from .tray import run_tray
        threading.Thread(target=run_tray, daemon=True).start()
    except Exception as e:
        logger.debug("Tray icon not available: %s", e)

    # FastAPI blocks the main thread
    run_server()


if __name__ == "__main__":
    main()
