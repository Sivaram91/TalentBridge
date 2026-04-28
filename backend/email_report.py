"""HTML email generation and sending — daily matches + weekly report + failure alerts."""
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_env() -> dict:
    env = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _read_smtp_config() -> dict:
    """Read sender SMTP config from smtp_config.json (operator-level setting)."""
    import json
    smtp_path = Path(__file__).parent.parent / "smtp_config.json"
    if smtp_path.exists():
        data = json.loads(smtp_path.read_text())
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}


def _send_email(subject: str, html_body: str):
    env = _read_env()
    smtp = _read_smtp_config()

    host = smtp.get("SMTP_HOST", "")
    port = int(smtp.get("SMTP_PORT", "587"))
    user = smtp.get("SMTP_USER", "")
    password = smtp.get("SMTP_PASS", "")
    recipient = env.get("REPORT_RECIPIENT", "")

    if not all([host, user, password, recipient]):
        raise ValueError("Email not fully configured — check smtp_config.json and recipient email in Settings")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(user, [recipient], msg.as_string())

    logger.info("Email sent: %s → %s", subject, recipient)


# ── Daily new-matches email ──────────────────────────────────────────────────

def send_daily_matches():
    """Send email only when there are new matched jobs since yesterday."""
    from .db import get_conn
    from .models import get_setting

    threshold = int(get_setting("match_threshold", "50"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.title, j.url, j.location, c.name AS company_name,
                   m.match_score, m.reasoning
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            JOIN matches m   ON m.job_id = j.id
            WHERE j.is_expired = 0
              AND m.match_score >= ?
              AND j.first_seen >= ?
            ORDER BY m.match_score DESC
        """, (threshold, cutoff)).fetchall()

    jobs = [dict(r) for r in rows]
    if not jobs:
        return  # nothing to send

    html = _render_daily_email(jobs)
    _send_email(f"TalentBridge — {len(jobs)} new matching job{'s' if len(jobs) != 1 else ''} today", html)


def _render_daily_email(jobs: list[dict]) -> str:
    rows = ""
    for j in jobs:
        title_link = f'<a href="{j["url"]}" style="color:#3b82f6;text-decoration:none">{j["title"]}</a>' if j.get("url") else j["title"]
        score_color = "#16a34a" if j["match_score"] >= 70 else "#d97706"
        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #e6e4df;font-size:14px;font-weight:500">{title_link}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #e6e4df;color:#7a7878;font-size:13px">{j["company_name"]}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #e6e4df">
            <span style="background:#f0fdf4;color:{score_color};padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;font-family:monospace">{j["match_score"]}%</span>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #e6e4df;color:#7a7878;font-size:12px">{j.get("reasoning","")}</td>
        </tr>"""

    return f"""<!DOCTYPE html><html><body style="font-family:'DM Sans',system-ui,sans-serif;background:#f4f3f1;padding:24px">
    <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e6e4df">
      <div style="background:#111318;padding:28px 32px">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.4);margin-bottom:6px">Daily Digest</div>
        <div style="font-size:20px;font-weight:700;color:#fff">New Matching Jobs</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:4px">{datetime.now().strftime("%d %B %Y").lstrip("0")}</div>
      </div>
      <div style="padding:24px 32px">
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="background:#f4f3f1">
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:600;color:#7a7878;text-transform:uppercase;letter-spacing:0.05em">Job</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:600;color:#7a7878;text-transform:uppercase;letter-spacing:0.05em">Company</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:600;color:#7a7878;text-transform:uppercase;letter-spacing:0.05em">Score</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:600;color:#7a7878;text-transform:uppercase;letter-spacing:0.05em">Why</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <div style="padding:14px 32px;background:#f4f3f1;border-top:1px solid #e6e4df;text-align:center;font-size:11px;color:#7a7878">
        Generated by TalentBridge · Running locally on your machine
      </div>
    </div></body></html>"""


# ── Weekly report ────────────────────────────────────────────────────────────

def build_weekly_report_data() -> dict:
    from .db import get_conn
    from .models import get_setting

    threshold = int(get_setting("match_threshold", "50"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    with get_conn() as conn:
        new_jobs = [dict(r) for r in conn.execute("""
            SELECT j.title, j.url, j.location, c.name AS company_name,
                   m.match_score, m.reasoning
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE j.is_expired = 0 AND j.first_seen >= ?
            ORDER BY COALESCE(m.match_score,0) DESC
            LIMIT 50
        """, (cutoff,)).fetchall()]

        matched_jobs = [dict(r) for r in conn.execute("""
            SELECT j.title, j.url, c.name AS company_name, m.match_score, m.reasoning
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            JOIN matches m ON m.job_id = j.id
            WHERE j.is_expired = 0 AND m.match_score >= ? AND j.first_seen >= ?
            ORDER BY m.match_score DESC
        """, (threshold, cutoff)).fetchall()]

        applied_jobs = [dict(r) for r in conn.execute("""
            SELECT j.title, j.url, c.name AS company_name, m.match_score
            FROM decisions d
            JOIN jobs j ON j.id = d.job_id
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE d.decision = 'applied' AND d.decided_at >= ?
            ORDER BY d.decided_at DESC
        """, (cutoff,)).fetchall()]

        skipped_jobs = [dict(r) for r in conn.execute("""
            SELECT j.title, j.url, c.name AS company_name, m.match_score, d.reason AS decision_reason
            FROM decisions d
            JOIN jobs j ON j.id = d.job_id
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE d.decision = 'skipped' AND d.decided_at >= ?
            ORDER BY d.decided_at DESC
        """, (cutoff,)).fetchall()]

    return {
        "new_jobs": new_jobs,
        "matched_jobs": matched_jobs,
        "applied_jobs": applied_jobs,
        "skipped_jobs": skipped_jobs,
        "week_start": (datetime.now() - timedelta(days=7)).strftime("%d %b").lstrip("0"),
        "week_end": datetime.now().strftime("%d %b %Y").lstrip("0"),
    }


def send_weekly_report():
    data = build_weekly_report_data()
    html = _render_weekly_email(data)
    week = datetime.now().strftime("CW%W %Y")
    _send_email(f"TalentBridge Weekly Report — {week}", html)


def _render_weekly_email(data: dict) -> str:
    def section(title: str, jobs: list, show_reason: bool = False) -> str:
        if not jobs:
            return ""
        rows = ""
        for j in jobs:
            score = j.get("match_score")
            score_html = ""
            if score is not None:
                color = "#16a34a" if score >= 70 else "#d97706" if score >= 50 else "#7a7878"
                score_html = f'<span style="background:#f9fafb;color:{color};padding:2px 7px;border-radius:99px;font-size:11px;font-weight:600;font-family:monospace;margin-right:8px">{score}%</span>'
            title_html = f'<a href="{j["url"]}" style="color:#3b82f6;text-decoration:none">{j["title"]}</a>' if j.get("url") else j["title"]
            reason_html = f'<span style="color:#7a7878;font-size:11px;font-style:italic"> · {j["decision_reason"]}</span>' if show_reason and j.get("decision_reason") else ""
            rows += f'<div style="display:flex;align-items:center;padding:8px 0;border-bottom:1px solid #f4f3f1">{score_html}<span style="font-size:13px;font-weight:500;flex:1">{title_html}</span><span style="color:#7a7878;font-size:12px">{j["company_name"]}</span>{reason_html}</div>'
        return f'<div style="margin-bottom:24px"><div style="font-size:11px;font-weight:700;color:#7a7878;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">{title}</div>{rows}</div>'

    content = (
        section("🆕 New Jobs This Week", data["new_jobs"]) +
        section("⭐ Matched Jobs (≥50%)", data["matched_jobs"]) +
        section("✅ Applied", data["applied_jobs"]) +
        section("⏭ Skipped", data["skipped_jobs"], show_reason=True)
    )

    stats = [
        (len(data["new_jobs"]), "New Jobs", "#3b82f6"),
        (len(data["matched_jobs"]), "Matched", "#16a34a"),
        (len(data["applied_jobs"]), "Applied", "#0d9488"),
        (len(data["skipped_jobs"]), "Skipped", "#7a7878"),
    ]
    stat_cells = "".join(
        f'<td style="text-align:center;padding:0 16px"><div style="font-size:28px;font-weight:700;color:{c};font-family:monospace">{v}</div><div style="font-size:11px;color:#7a7878;margin-top:2px">{l}</div></td>'
        for v, l, c in stats
    )

    return f"""<!DOCTYPE html><html><body style="font-family:'DM Sans',system-ui,sans-serif;background:#f4f3f1;padding:24px">
    <div style="max-width:660px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e6e4df">
      <div style="background:#111318;padding:32px 36px">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.4);margin-bottom:8px">Weekly Digest</div>
        <div style="font-size:22px;font-weight:700;color:#fff">TalentBridge Report</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.55);margin-top:4px">{data["week_start"]} – {data["week_end"]}</div>
      </div>
      <div style="padding:28px 36px">
        <table style="width:100%;margin-bottom:28px;padding-bottom:24px;border-bottom:1px solid #e6e4df"><tr>{stat_cells}</tr></table>
        {content}
      </div>
      <div style="padding:16px 36px;background:#f4f3f1;border-top:1px solid #e6e4df;text-align:center;font-size:11px;color:#7a7878">
        Generated by TalentBridge · Running locally on your machine
      </div>
    </div></body></html>"""


# ── Failure alert ─────────────────────────────────────────────────────────────

def send_failure_alert(company: dict, consecutive_failures: int):
    html = f"""<!DOCTYPE html><html><body style="font-family:system-ui,sans-serif;background:#f4f3f1;padding:24px">
    <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:28px;border:1px solid #e6e4df">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px">⚠️ Scrape Failure Alert</div>
      <p style="color:#7a7878;font-size:14px;margin:0 0 16px">
        <strong style="color:#18181a">{company["name"]}</strong> has failed to scrape
        {consecutive_failures} times in a row.
      </p>
      <p style="color:#7a7878;font-size:13px;margin:0">
        This usually means the site structure changed or the site is down.<br>
        Check the career portal: <a href="{company["url"]}">{company["url"]}</a>
      </p>
    </div></body></html>"""

    try:
        _send_email(f"TalentBridge — Scrape failure: {company['name']}", html)
    except Exception as e:
        logger.error("Could not send failure alert: %s", e)
