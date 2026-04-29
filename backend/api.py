"""FastAPI application — routes for UI and REST endpoints."""
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import get_conn
from .models import (
    get_all_companies, get_company, get_jobs_for_company,
    get_latest_cv, save_cv, set_extra_keywords, set_keyword_types,
    get_all_decided_jobs, save_decision,
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

app = FastAPI(title="TalentBridge")

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
    return _tr(request, "companies.html", {
        "companies": companies,
        "jobs_by_company": jobs_by_company,
        "threshold": threshold,
        "active_nav": "companies",
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
    except Exception:
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
async def report_page(request: Request):
    from .email_report import build_weekly_report_data
    data = build_weekly_report_data()
    return _tr(request, "report.html", {
        "data": data,
        "active_nav": "report",
    })


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
    from .matcher import run_matching
    await run_matching()
    return JSONResponse({"ok": True})


@app.post("/api/taxonomy/build")
async def api_taxonomy_build():
    from .skill_taxonomy import build_taxonomy
    try:
        skills = await build_taxonomy()
        return JSONResponse({"ok": True, "count": len(skills)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/taxonomy/status")
async def api_taxonomy_status():
    from .models import get_setting
    raw = get_setting("skill_taxonomy_json", "[]")
    try:
        skills = json.loads(raw)
    except Exception:
        skills = []
    return JSONResponse({"count": len(skills), "built": len(skills) > 0})


@app.get("/api/taxonomy/skills")
async def api_taxonomy_skills():
    from .skill_taxonomy import get_taxonomy
    return JSONResponse(get_taxonomy())


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
    asyncio.create_task(run_scrape())
    return JSONResponse({"ok": True, "message": "Scrape started"})


@app.post("/api/descriptions/fetch")
async def api_fetch_descriptions():
    import asyncio
    from .scraper import _fetch_all_descriptions, _desc_fetch_active
    if _desc_fetch_active > 0:
        return JSONResponse({"ok": False, "message": "Description fetching already in progress"}, status_code=409)
    with get_conn() as conn:
        company_ids = [r["company_id"] for r in conn.execute(
            "SELECT DISTINCT company_id FROM jobs WHERE is_expired=0 AND url != ''"
        ).fetchall()]
    if not company_ids:
        return JSONResponse({"ok": False, "message": "No jobs with URLs found"})
    # Reset run counters so progress starts from 0/total
    from .scraper import _desc_fetch_done, _desc_fetch_total  # noqa — we'll set via module
    import backend.scraper as _scraper_mod
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_expired=0 AND url != ''"
        ).fetchone()[0]
    _scraper_mod._desc_fetch_done  = 0
    _scraper_mod._desc_fetch_total = total
    for cid in company_ids:
        asyncio.create_task(_fetch_all_descriptions(cid, force=True))
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
    return JSONResponse({
        "total": total,
        "fetched": fetched,
        "fetching": fetching,
        "active_tasks": _scraper_mod._desc_fetch_active,
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
