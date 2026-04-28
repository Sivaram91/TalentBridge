"""System tray icon using pystray."""
import threading
import webbrowser
import logging

logger = logging.getLogger(__name__)

PORT = 7070


def _open_dashboard():
    webbrowser.open(f"http://localhost:{PORT}")


def _scrape_now():
    import urllib.request
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://localhost:{PORT}/api/scrape/now",
                method="POST",
            ),
            timeout=5,
        )
    except Exception as e:
        logger.warning("Could not trigger scrape from tray: %s", e)


def run_tray():
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("pystray/Pillow not installed — tray icon disabled")
        return

    # Draw a simple icon
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(8, 52), (32, 12), (56, 52)], fill=(88, 166, 255))

    paused = threading.Event()

    def on_open(icon, item):
        _open_dashboard()

    def on_scrape_now(icon, item):
        _scrape_now()

    def on_quit(icon, item):
        icon.stop()
        import os, signal
        os.kill(os.getpid(), signal.SIGTERM)

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", on_open, default=True),
        pystray.MenuItem("Run Scrape Now", on_scrape_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit TalentBridge", on_quit),
    )

    icon = pystray.Icon("TalentBridge", img, "TalentBridge", menu)
    icon.run()
