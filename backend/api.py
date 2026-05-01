"""FastAPI application — routes for UI and REST endpoints."""
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import get_conn
from .models import (
    get_all_companies, get_company, get_jobs_for_company,
    get_latest_cv, save_cv, set_extra_keywords, set_keyword_types,
    get_all_decided_jobs, get_all_active_jobs, save_decision,
    set_match_override,
    get_setting, set_setting, ensure_settings_table,
    get_scrape_log,
    get_jobs_summary_by_company,
    search_jobs_by_keyword,
)

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"
ENV_PATH = BASE_DIR / ".env"

@asynccontextmanager
async def _lifespan(app: FastAPI):
    import logging as _ll
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    _ll.getLogger().setLevel(_ll.INFO)
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        _ll.getLogger(noisy).setLevel(_ll.WARNING)
    # Tag any existing jobs that predate the tagging system
    try:
        from .tagger import tag_untagged_jobs
        await asyncio.get_event_loop().run_in_executor(None, tag_untagged_jobs)
    except Exception as e:
        _ll.getLogger(__name__).warning("Startup tagging failed: %s", e)
    try:
        yield
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass  # suppress shutdown noise from in-flight SSE connections

app = FastAPI(title="TalentBridge", lifespan=_lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(data: dict):
    lines = [f"{k}={v}" for k, v in data.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n")


def _tr(request: Request, name: str, context: dict) -> HTMLResponse:
    """TemplateResponse wrapper — Starlette 0.36+ keyword-arg signature."""
    context["request"] = request
    return templates.TemplateResponse(request=request, name=name, context=context)


def _safe_task(coro, name: str = "task"):
    """Wrap a coroutine in create_task so exceptions are logged instead of silently lost."""
    async def _run():
        try:
            await coro
        except Exception as exc:
            logger.error("Background task '%s' failed: %s", name, exc, exc_info=True)

    return asyncio.create_task(_run())


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/companies")


# ── Company Overview ──────────────────────────────────────────────────────────

@app.get("/companies", response_class=HTMLResponse)
async def companies_page(request: Request):
    companies = get_all_companies()
    jobs_by_company = get_jobs_summary_by_company()
    threshold = int(get_setting("match_threshold", "50"))
    view = request.query_params.get("view", "companies")
    return _tr(request, "companies.html", {
        "companies": companies,
        "jobs_by_company": jobs_by_company,
        "threshold": threshold,
        "active_nav": view if view == "jobs" else "companies",
    })


# ── Per-Company View ──────────────────────────────────────────────────────────

@app.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(request: Request, company_id: int):
    company = get_company(company_id)
    if not company:
        raise HTTPException(404)
    jobs = get_jobs_for_company(company_id)
    for j in jobs:
        if j.get("match_score") is None:
            j["match_score"] = -1
    scrape_log = get_scrape_log(company_id, limit=5)
    threshold = int(get_setting("match_threshold", "50"))
    return _tr(request, "company_detail.html", {
        "company": company,
        "jobs": jobs,
        "scrape_log": scrape_log,
        "threshold": threshold,
        "active_nav": "companies",
    })


# ── Jobs (all companies) ──────────────────────────────────────────────────────

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return RedirectResponse(url="/companies?view=jobs", status_code=302)


# ── CV Manager ────────────────────────────────────────────────────────────────

@app.get("/cv", response_class=HTMLResponse)
async def cv_page(request: Request):
    cv = get_latest_cv()
    keywords = json.loads(cv["keywords_json"]) if cv else []
    extra_keywords = json.loads(cv["extra_keywords_json"]) if cv else []
    keyword_types = json.loads(cv["keyword_types_json"]) if cv else {}
    return _tr(request, "cv.html", {
        "cv": cv,
        "keywords": keywords,
        "extra_keywords": extra_keywords,
        "keyword_types": keyword_types,
        "active_nav": "cv",
    })


@app.post("/cv/upload")
async def cv_upload(file: UploadFile = File(...)):
    content = await file.read()
    filename = file.filename or "cv"

    if filename.lower().endswith(".pdf"):
        raw_text = _extract_pdf_text(content)
    else:
        raw_text = content.decode("utf-8", errors="replace")

    save_cv(raw_text, [])

    try:
        from .gemini import extract_cv_keywords
        keywords = await extract_cv_keywords(raw_text)
        with get_conn() as conn:
            cv_row = conn.execute(
                "SELECT id FROM cv ORDER BY uploaded_at DESC LIMIT 1"
            ).fetchone()
            if cv_row:
                conn.execute(
                    "UPDATE cv SET keywords_json=? WHERE id=?",
                    (json.dumps(keywords), cv_row["id"])
                )
    except Exception as e:
        logger.error("CV keyword extraction failed: %s", e, exc_info=True)
        keywords = []

    return JSONResponse({"ok": True, "keywords": keywords})


@app.post("/cv/keywords")
async def cv_save_extra_keywords(keywords: list[str]):
    cv = get_latest_cv()
    if not cv:
        raise HTTPException(400, "No CV uploaded yet")
    set_extra_keywords(cv["id"], keywords)
    return JSONResponse({"ok": True})


@app.post("/cv/keyword-types")
async def cv_save_keyword_types(types: dict[str, str]):
    cv = get_latest_cv()
    if not cv:
        raise HTTPException(400, "No CV uploaded yet")
    set_keyword_types(cv["id"], types)
    return JSONResponse({"ok": True})


@app.get("/api/experience-level")
async def get_experience_level():
    return JSONResponse({"level": get_setting("experience_level", "senior")})


@app.post("/api/experience-level")
async def set_experience_level(body: dict):
    level = body.get("level", "senior")
    set_setting("experience_level", level)
    return JSONResponse({"ok": True})


@app.get("/api/preferred-countries")
async def get_preferred_countries():
    import json as _json
    raw = get_setting("preferred_countries", "[]")
    try:
        countries = _json.loads(raw)
    except Exception:
        countries = []
    return JSONResponse({"countries": countries})


@app.post("/api/preferred-countries")
async def set_preferred_countries(body: dict):
    import json as _json
    countries = body.get("countries", [])
    set_setting("preferred_countries", _json.dumps(countries, ensure_ascii=False))
    return JSONResponse({"ok": True})


def _extract_pdf_text(content: bytes) -> str:
    try:
        import pypdf, io
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        return content.decode("utf-8", errors="replace")


# ── Application Tracker ───────────────────────────────────────────────────────

@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    jobs = get_all_decided_jobs()
    counts = {
        "all": len(jobs),
        "interested": sum(1 for j in jobs if j["decision"] == "interested"),
        "applied": sum(1 for j in jobs if j["decision"] == "applied"),
        "skipped": sum(1 for j in jobs if j["decision"] == "skipped"),
    }
    return _tr(request, "tracker.html", {
        "jobs": jobs,
        "counts": counts,
        "active_nav": "tracker",
    })


# ── Weekly Report ─────────────────────────────────────────────────────────────

@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, week: int = 0):
    from .email_report import build_weekly_report_data
    data = build_weekly_report_data(week_offset=week)
    return _tr(request, "report.html", {
        "data": data,
        "active_nav": "report",
    })


@app.get("/api/report/weeks")
async def report_weeks():
    from .email_report import get_available_weeks
    return {"weeks": get_available_weeks()}


@app.post("/report/send")
async def report_send():
    try:
        from .email_report import send_weekly_report
        send_weekly_report()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Alert Settings (recipient email + schedule) ───────────────────────────────

@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    env = _read_env()
    return _tr(request, "alerts.html", {
        "report_recipient": env.get("REPORT_RECIPIENT", ""),
        "scrape_time": get_setting("scrape_time", "07:00"),
        "report_day": get_setting("report_day", "monday"),
        "report_time": get_setting("report_time", "08:00"),
        "match_threshold": get_setting("match_threshold", "50"),
        "active_nav": "alerts",
    })


@app.post("/alerts")
async def alerts_save(
    report_recipient: str = Form(""),
    scrape_time: str = Form("07:00"),
    report_day: str = Form("monday"),
    report_time: str = Form("08:00"),
    match_threshold: str = Form("50"),
):
    env = _read_env()
    env["REPORT_RECIPIENT"] = report_recipient
    _write_env(env)
    set_setting("scrape_time", scrape_time)
    set_setting("report_day", report_day)
    set_setting("report_time", report_time)
    set_setting("match_threshold", match_threshold)
    return RedirectResponse("/alerts", status_code=303)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.post("/api/decisions/{job_id}")
async def api_set_decision(
    job_id: int,
    decision: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
):
    save_decision(job_id, decision, reason)
    return JSONResponse({"ok": True})


@app.delete("/api/decisions/{job_id}")
async def api_clear_decision(job_id: int):
    save_decision(job_id, None, None)
    return JSONResponse({"ok": True})


@app.post("/api/matches/{job_id}/override")
async def api_override_match(job_id: int, score: int = Form(...)):
    set_match_override(job_id, score)
    return JSONResponse({"ok": True})


@app.post("/api/match/now")
async def api_match_now():
    import asyncio
    from .matcher import run_matching, _matching_active
    if _matching_active:
        return JSONResponse({"ok": True, "started": False, "message": "Already running"})
    _safe_task(run_matching(), name="matching")
    return JSONResponse({"ok": True, "started": True})


@app.get("/api/match/status")
async def api_match_status():
    from .matcher import _matching_active, _matching_started_at
    return JSONResponse({"running": _matching_active, "started_at": _matching_started_at})


_taxonomy_building = False

@app.post("/api/taxonomy/build")
async def api_taxonomy_build():
    import asyncio
    global _taxonomy_building
    if _taxonomy_building:
        return JSONResponse({"ok": False, "message": "Build already in progress"}, status_code=409)

    async def _run():
        global _taxonomy_building
        _taxonomy_building = True
        try:
            from .skill_taxonomy import build_taxonomy, build_clusters
            taxonomy = await build_taxonomy()
            if taxonomy:
                await build_clusters(taxonomy)
        except Exception as e:
            logger.error("Taxonomy build failed: %s", e)
        finally:
            _taxonomy_building = False

    _safe_task(_run(), name="taxonomy-build")
    return JSONResponse({"ok": True, "message": "Build started"})


@app.get("/api/taxonomy/status")
async def api_taxonomy_status():
    from .models import get_setting
    from .db import get_conn
    raw = get_setting("skill_taxonomy_json", "[]")
    try:
        skills = json.loads(raw)
    except Exception:
        skills = []
    with get_conn() as conn:
        cluster_count = conn.execute("SELECT COUNT(*) FROM skill_clusters").fetchone()[0]
    return JSONResponse({
        "count": len(skills),
        "built": len(skills) > 0,
        "building": _taxonomy_building,
        "clusters": cluster_count,
    })


@app.get("/api/taxonomy/skills")
async def api_taxonomy_skills():
    from .skill_taxonomy import get_taxonomy
    return JSONResponse(get_taxonomy())


@app.get("/api/taxonomy/clusters")
async def api_taxonomy_clusters():
    from .skill_taxonomy import get_clusters
    return JSONResponse(get_clusters())


# ── Console log — SSE stream + file persistence ───────────────────────────────

import asyncio
import logging as _logging
from datetime import datetime
from fastapi.responses import StreamingResponse

_LOG_DIR = BASE_DIR / "data" / "logs"
_LOG_MAX_LINES = 2000
_log_current_file: Path | None = None
_log_current_lines: int = 0

# Subscribers: set of asyncio.Queue, one per connected SSE client
_log_subscribers: set[asyncio.Queue] = set()
_event_loop: asyncio.AbstractEventLoop | None = None



def _get_log_file() -> Path:
    global _log_current_file, _log_current_lines
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    if _log_current_file is None or _log_current_lines >= _LOG_MAX_LINES:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_current_file = _LOG_DIR / f"console_{ts}.txt"
        _log_current_lines = 0
    return _log_current_file


def _write_log_line(line: str):
    global _log_current_lines
    log_file = _get_log_file()
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    _log_current_lines += 1


def _broadcast_log(line: str):
    """Write to file and thread-safely push to all SSE subscribers."""
    _write_log_line(line)
    if not _event_loop or not _log_subscribers:
        return
    def _push():
        for q in list(_log_subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass
    try:
        _event_loop.call_soon_threadsafe(_push)
    except RuntimeError:
        pass


class _SSELogHandler(_logging.Handler):
    LEVEL_MAP = {
        _logging.DEBUG:    "debug",
        _logging.INFO:     "info",
        _logging.WARNING:  "warn",
        _logging.ERROR:    "error",
        _logging.CRITICAL: "error",
    }

    def emit(self, record: _logging.LogRecord):
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            level = self.LEVEL_MAP.get(record.levelno, "info")
            msg = self.format(record)
            line = f"[{level.upper()}] {ts}  {msg}"
            _broadcast_log(line)
        except Exception:
            pass


# Attach to root logger — level will be set to INFO on startup
_sse_handler = _SSELogHandler()
_sse_handler.setFormatter(_logging.Formatter("%(name)s — %(message)s"))
_sse_handler.setLevel(_logging.DEBUG)
_logging.getLogger().addHandler(_sse_handler)


@app.get("/api/console/stream")
async def api_console_stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _log_subscribers.add(q)

    async def event_gen():
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15)
                    # SSE format
                    yield f"data: {json.dumps(line)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # prevent connection timeout
        except asyncio.CancelledError:
            pass
        finally:
            _log_subscribers.discard(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/console/log")
async def api_console_log(request: Request):
    """Accept log lines from the frontend (UI-side events like button clicks)."""
    body = await request.json()
    lines: list[str] = body if isinstance(body, list) else [body]
    for line in lines:
        _broadcast_log(line)
    return JSONResponse({"ok": True})


@app.post("/api/taxonomy/skills")
async def api_taxonomy_skills_save(skills: list[str]):
    set_setting("skill_taxonomy_json", json.dumps(skills, ensure_ascii=False))
    set_setting("skill_taxonomy_count", str(len(skills)))
    return JSONResponse({"ok": True, "count": len(skills)})


@app.post("/api/scrape/now")
async def api_scrape_now():
    from .scraper import run_scrape, _scrape_lock
    import asyncio
    if _scrape_lock.locked():
        return JSONResponse({"ok": False, "message": "Scrape already in progress"}, status_code=409)
    _safe_task(run_scrape(), name="scrape")
    return JSONResponse({"ok": True, "message": "Scrape started"})


@app.post("/api/descriptions/cancel")
async def api_cancel_descriptions():
    import backend.scraper as _scraper_mod
    if _scraper_mod._desc_fetch_active == 0:
        return JSONResponse({"ok": False, "message": "No fetch in progress"})
    _scraper_mod._desc_fetch_cancel = True
    return JSONResponse({"ok": True, "message": "Cancel requested"})


@app.post("/api/descriptions/fetch")
async def api_fetch_descriptions():
    import asyncio
    import backend.scraper as _scraper_mod
    from .scraper import _fetch_all_descriptions
    if _scraper_mod._desc_fetch_active > 0:
        return JSONResponse({"ok": False, "message": "Description fetching already in progress"}, status_code=409)
    with get_conn() as conn:
        company_ids = [r["company_id"] for r in conn.execute(
            "SELECT DISTINCT company_id FROM jobs WHERE is_expired=0 AND url != ''"
        ).fetchall()]
    if not company_ids:
        return JSONResponse({"ok": False, "message": "No jobs with URLs found"})
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_expired=0 AND url != ''"
        ).fetchone()[0]
    # Reset counters and cancel flag for fresh run
    _scraper_mod._desc_fetch_done   = 0
    _scraper_mod._desc_fetch_total  = total
    _scraper_mod._desc_fetch_cancel = False
    for cid in company_ids:
        _safe_task(_fetch_all_descriptions(cid, force=True), name=f"desc-fetch-{cid}")
    # Also resolve countries for jobs that already have location but no country
    import threading
    from .main import _resolve_missing_countries
    threading.Thread(target=_resolve_missing_countries, daemon=True).start()
    return JSONResponse({"ok": True, "message": f"Fetching descriptions for {len(company_ids)} companies"})


@app.get("/api/descriptions/status")
async def api_descriptions_status():
    import backend.scraper as _scraper_mod
    fetching = _scraper_mod._desc_fetch_active > 0
    if fetching and _scraper_mod._desc_fetch_total > 0:
        # Show run-level progress while fetch is active
        fetched = _scraper_mod._desc_fetch_done
        total   = _scraper_mod._desc_fetch_total
    else:
        with get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN description IS NOT NULL AND description != '' THEN 1 END) AS fetched
                FROM jobs WHERE is_expired=0
            """).fetchone()
        fetched = row["fetched"]
        total   = row["total"]
    # Always query per-company counts from DB (reflects live writes)
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT company_id,
                   COUNT(*) AS total,
                   COUNT(CASE WHEN description IS NOT NULL AND description != '' THEN 1 END) AS fetched
            FROM jobs WHERE is_expired=0
            GROUP BY company_id
        """).fetchall()
    by_company = {str(r["company_id"]): {"fetched": r["fetched"], "total": r["total"]} for r in rows}
    # Extract just the domain/path tail for display (avoid showing full URL)
    current_url = _scraper_mod._desc_fetch_current or ""
    try:
        from urllib.parse import urlparse
        p = urlparse(current_url)
        current_display = p.netloc + (p.path[:40] if len(p.path) > 40 else p.path)
    except Exception:
        current_display = current_url[:60]
    return JSONResponse({
        "total": total,
        "fetched": fetched,
        "fetching": fetching,
        "active_tasks": _scraper_mod._desc_fetch_active,
        "current_url": current_display,
        "by_company": by_company,
    })


@app.get("/api/jobs/search")
async def api_jobs_search(q: str = ""):
    q = q.strip()
    if len(q) < 2:
        return JSONResponse({"query": q, "results": {}})
    results = search_jobs_by_keyword(q)
    return JSONResponse({"query": q, "results": {str(k): v for k, v in results.items()}})


@app.get("/api/status")
async def api_status():
    import time
    from .scraper import _scrape_lock, _scrape_started_at
    from .matcher import _matching_active, _matching_started_at
    companies = get_all_companies()
    pending = sum(1 for c in companies if c.get("scrape_status") == "pending")
    failed = sum(1 for c in companies if c.get("scrape_status") == "failed")
    scraping = _scrape_lock.locked()
    matching = _matching_active
    now = time.monotonic()
    return JSONResponse({
        "companies": len(companies),
        "pending": pending,
        "failed": failed,
        "scraping": scraping,
        "scraping_elapsed": int(now - _scrape_started_at) if scraping else 0,
        "matching": matching,
        "matching_elapsed": int(now - _matching_started_at) if matching else 0,
    })
