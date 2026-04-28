"""OS startup registration — Windows startup entry / Mac launchd / Linux systemd."""
import os
import sys
import platform
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "TalentBridge"
EXE_PATH = Path(sys.executable).resolve()


def register_startup():
    """Register the app to run at OS startup."""
    system = platform.system()
    try:
        if system == "Windows":
            _register_windows()
        elif system == "Darwin":
            _register_mac()
        elif system == "Linux":
            _register_linux()
    except Exception as e:
        logger.warning("Could not register startup: %s", e)


def unregister_startup():
    """Remove from OS startup."""
    system = platform.system()
    try:
        if system == "Windows":
            _unregister_windows()
        elif system == "Darwin":
            _unregister_mac()
        elif system == "Linux":
            _unregister_linux()
    except Exception as e:
        logger.warning("Could not unregister startup: %s", e)


# ── Windows ───────────────────────────────────────────────────────────────────

def _register_windows():
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE,
    )
    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, str(EXE_PATH))
    winreg.CloseKey(key)
    logger.info("Registered Windows startup: %s", EXE_PATH)


def _unregister_windows():
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE,
    )
    try:
        winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass
    winreg.CloseKey(key)


# ── macOS ─────────────────────────────────────────────────────────────────────

_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.talentbridge.app.plist"

_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.talentbridge.app</string>
    <key>ProgramArguments</key>
    <array><string>{exe}</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>"""


def _register_mac():
    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(_PLIST_TEMPLATE.format(exe=EXE_PATH))
    os.system(f"launchctl load {_PLIST_PATH}")
    logger.info("Registered macOS launchd: %s", _PLIST_PATH)


def _unregister_mac():
    if _PLIST_PATH.exists():
        os.system(f"launchctl unload {_PLIST_PATH}")
        _PLIST_PATH.unlink()


# ── Linux ─────────────────────────────────────────────────────────────────────

_SYSTEMD_PATH = Path.home() / ".config" / "systemd" / "user" / "talentbridge.service"

_SYSTEMD_TEMPLATE = """[Unit]
Description=TalentBridge job tracker
After=network.target

[Service]
ExecStart={exe}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def _register_linux():
    _SYSTEMD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SYSTEMD_PATH.write_text(_SYSTEMD_TEMPLATE.format(exe=EXE_PATH))
    os.system("systemctl --user daemon-reload")
    os.system("systemctl --user enable talentbridge.service")
    os.system("systemctl --user start talentbridge.service")
    logger.info("Registered systemd user service")


def _unregister_linux():
    if _SYSTEMD_PATH.exists():
        os.system("systemctl --user stop talentbridge.service")
        os.system("systemctl --user disable talentbridge.service")
        _SYSTEMD_PATH.unlink()
