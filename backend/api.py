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
    get_latest_cv, save_cv,
    get_all_decided_jobs, save_decision,
    set_match_override,
    get_setting, set_setting, ensure_settings_table,
    get_scrape_log,
)

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"
ENV_PATH = BASE_DIR / ".env"

app = FastAPI(title="TalentBridge")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
    return _tr(request, "companies.html", {
        "companies": companies,
        "active_nav": "companies",
    })


# ── Per-Company View ──────────────────────────────────────────────────────────

@app.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(request: Request, company_id: int):
    company = get_company(company_id)
    if not company:
        raise HTTPException(404)
    jobs = get_jobs_for_company(company_id)
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
    return _tr(request, "cv.html", {
        "cv": cv,
        "keywords": keywords,
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


@app.post("/api/scrape/now")
async def api_scrape_now():
    from .scraper import run_scrape
    import asyncio
    asyncio.create_task(run_scrape())
    return JSONResponse({"ok": True, "message": "Scrape started"})


@app.get("/api/status")
async def api_status():
    companies = get_all_companies()
    pending = sum(1 for c in companies if c.get("scrape_status") == "pending")
    failed = sum(1 for c in companies if c.get("scrape_status") == "failed")
    return JSONResponse({
        "companies": len(companies),
        "pending": pending,
        "failed": failed,
    })
