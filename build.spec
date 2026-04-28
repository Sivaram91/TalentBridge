# PyInstaller spec — builds TalentBridge into a single executable
# Run with: pyinstaller build.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
        (str(ROOT / "partners.json"), "."),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "apscheduler.schedulers.background",
        "apscheduler.triggers.cron",
        "apscheduler.jobstores.memory",
        "apscheduler.executors.pool",
        "pystray._win32",
        "pystray._darwin",
        "pystray._gtk",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "playwright",
        "pypdf",
        "httpx",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="TalentBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no console window
    icon=None,  # add icon path here if desired
    onefile=True,
)
