"""Thin query helpers — no ORM, plain SQL via db.get_conn()."""
import json
import logging
from typing import Optional
from .db import get_conn

logger = logging.getLogger(__name__)


# ── Companies ────────────────────────────────────────────────────────────────

def get_all_companies():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                c.id, c.name, c.url, c.added_date,
                c.fetch, c.method, c.job_link_selector, c.title_selector,
                c.pagination_json, c.api_body_json, c.job_base_url, c.portal_url,
                COUNT(CASE WHEN j.is_expired=0 THEN 1 END)                        AS active_job_count,
                COUNT(CASE WHEN j.is_expired=0 AND j.description IS NOT NULL AND j.description!='' THEN 1 END) AS desc_fetched_count,
                (SELECT COUNT(*) FROM matches m
                 JOIN jobs j2 ON m.job_id=j2.id
                 WHERE j2.company_id=c.id AND j2.is_expired=0
                   AND m.match_score >= (
                       SELECT CAST(value AS INTEGER)
                       FROM settings WHERE key='match_threshold' LIMIT 1)
                )                                                     AS matched_job_count,
                sl.scraped_at  AS last_scraped,
                sl.status      AS scrape_status
            FROM companies c
            LEFT JOIN jobs j       ON j.company_id = c.id
            LEFT JOIN (
                SELECT company_id, scraped_at, status,
                       ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY scraped_at DESC) rn
                FROM scrape_log
            ) sl ON sl.company_id = c.id AND sl.rn = 1
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall()
    return [dict(r) for r in rows]


def _query_variants(query: str) -> list[str]:
    q = query.strip().lower()
    variants = {
        q,
        q.replace(" ", ""),
        q.replace(" ", "-"),
        q.replace("-", " "),
        q.replace("-", ""),
    }
    return [v for v in variants if v]


def search_jobs_by_keyword(query: str):
    """Search title, description, location with variant expansion and fuzzy title matching."""
    import difflib
    variants = _query_variants(query)
    tokens = [w for w in query.lower().split() if len(w) > 3]
    search_terms = list(set(variants + tokens))

    with get_conn() as conn:
        all_jobs = conn.execute(
            "SELECT id, company_id, title FROM jobs WHERE is_expired=0"
        ).fetchall()

        conds = " OR ".join(
            ["(j.title LIKE ? OR j.description LIKE ? OR j.location LIKE ?)"] * len(search_terms)
        )
        params = []
        for t in search_terms:
            like = f"%{t}%"
            params += [like, like, like]
        like_rows = conn.execute(
            f"SELECT id FROM jobs j WHERE is_expired=0 AND ({conds})", params
        ).fetchall()

    matched_ids = {r["id"] for r in like_rows}

    # Fuzzy pass on titles for typo tolerance (ratio >= 0.75)
    q_lower = query.lower()
    for job in all_jobs:
        if job["id"] not in matched_ids:
            if difflib.SequenceMatcher(None, q_lower, (job["title"] or "").lower()).ratio() >= 0.75:
                matched_ids.add(job["id"])

    result = {}
    for job in all_jobs:
        if job["id"] not in matched_ids:
            continue
        cid = job["company_id"]
        if cid not in result:
            result[cid] = {"count": 0, "job_ids": []}
        result[cid]["count"] += 1
        result[cid]["job_ids"].append(str(job["id"]))

    return {cid: {"count": v["count"], "job_ids": ",".join(v["job_ids"])}
            for cid, v in result.items()}


def get_jobs_summary_by_company():
    """Returns {company_id: [{...}, ...]} for active jobs, including tag columns."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.id, j.company_id, j.title, j.location, j.country,
                   j.url, j.description, j.posted_date, j.first_seen,
                   j.level_tag, j.profile_tags, j.location_tags,
                   c.name AS company_name,
                   COALESCE(m.match_score, -1) AS score,
                   m.reasoning,
                   d.decision, d.reason AS decision_reason
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches m ON m.job_id = j.id
            LEFT JOIN decisions d ON d.job_id = j.id
            WHERE j.is_expired = 0
        """).fetchall()
    result = {}
    for r in rows:
        cid = r["company_id"]
        if cid not in result:
            result[cid] = []
        result[cid].append({
            "id": r["id"],
            "title": r["title"] or "",
            "location": r["location"] or "",
            "country": r["country"] or "",
            "level_tag": r["level_tag"] or "Others",
            "profile_tags": json.loads(r["profile_tags"] or "[]"),
            "location_tags": json.loads(r["location_tags"] or "[]"),
            "score": r["score"],
            "url": r["url"] or "",
            "description": r["description"] or "",
            "reasoning": r["reasoning"] or "",
            "decision": r["decision"],
            "decision_reason": r["decision_reason"],
            "posted_date": r["posted_date"],
            "first_seen": r["first_seen"],
            "company_name": r["company_name"] or "",
            "company_id": cid,
        })
    return result


def get_company(company_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    return dict(row) if row else None


def upsert_company(name: str, url: str, fetch: str = "http", method: str = "css",
                   job_link_selector: str = "", title_selector: str = "",
                   pagination_json: str = "{}", api_body_json: str = "{}",
                   job_base_url: str = "", portal_url: str = "") -> int:
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE companies SET url=?, fetch=?, method=?, job_link_selector=?,
                   title_selector=?, pagination_json=?, api_body_json=?, job_base_url=?,
                   portal_url=? WHERE id=?""",
                (url, fetch, method, job_link_selector, title_selector,
                 pagination_json, api_body_json, job_base_url, portal_url, existing["id"])
            )
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO companies (name, url, fetch, method, job_link_selector,
               title_selector, pagination_json, api_body_json, job_base_url, portal_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (name, url, fetch, method, job_link_selector, title_selector,
             pagination_json, api_body_json, job_base_url, portal_url)
        )
        return cur.lastrowid


# ── Jobs ─────────────────────────────────────────────────────────────────────

def get_jobs_for_company(company_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.*,
                   m.match_score, m.reasoning, m.is_override, m.override_value,
                   d.decision, d.reason AS decision_reason, d.decided_at
            FROM jobs j
            LEFT JOIN matches   m ON m.job_id = j.id
            LEFT JOIN decisions d ON d.job_id = j.id
            WHERE j.company_id = ?
            ORDER BY j.is_expired ASC, COALESCE(m.match_score,0) DESC
        """, (company_id,)).fetchall()
    return [dict(r) for r in rows]


def upsert_job(company_id: int, title: str, description: str,
               url: str, location: str) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, url FROM jobs WHERE company_id=? AND title=? AND is_expired=0",
            (company_id, title)
        ).fetchone()
        if existing:
            # If title AND url match, the job is unchanged — only touch last_seen
            if existing["url"] == url:
                conn.execute(
                    "UPDATE jobs SET last_seen=datetime('now') WHERE id=?",
                    (existing["id"],)
                )
            elif description:
                conn.execute(
                    "UPDATE jobs SET last_seen=datetime('now'), description=?, url=?, location=? WHERE id=?",
                    (description, url, location, existing["id"])
                )
            else:
                conn.execute(
                    "UPDATE jobs SET last_seen=datetime('now'), url=?, location=? WHERE id=?",
                    (url, location, existing["id"])
                )
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO jobs (company_id, title, description, url, location) VALUES (?,?,?,?,?)",
            (company_id, title, description, url, location)
        )
        return cur.lastrowid


def mark_expired_jobs(company_id: int, seen_titles: list[str]):
    """Jobs not in seen_titles are marked expired.

    Safety: if the new scrape returned fewer than 30% of the previously known
    active jobs, skip expiry — the scrape likely failed or was truncated.
    """
    with get_conn() as conn:
        prev_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE company_id=? AND is_expired=0",
            (company_id,)
        ).fetchone()[0]
        # Only expire if we saw a reasonable fraction of what was there before
        if prev_count > 0 and len(seen_titles) < prev_count * 0.30:
            return
        conn.execute("""
            UPDATE jobs SET is_expired=1
            WHERE company_id=? AND is_expired=0
              AND title NOT IN ({})
        """.format(",".join("?" * len(seen_titles))),
            [company_id] + seen_titles
        )


def get_all_active_jobs():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.id, j.title, j.location, j.url, j.first_seen, j.posted_date,
                   j.description, j.level_tag, j.profile_tags, j.location_tags,
                   c.id AS company_id, c.name AS company_name,
                   m.match_score, m.reasoning,
                   d.decision, d.reason AS decision_reason
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches   m ON m.job_id = j.id
            LEFT JOIN decisions d ON d.job_id = j.id
            WHERE j.is_expired = 0
            ORDER BY COALESCE(m.match_score, -1) DESC, c.name, j.title
        """).fetchall()
    return [dict(r) for r in rows]


def get_all_decided_jobs():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.*, c.name AS company_name,
                   m.match_score, m.reasoning,
                   d.decision, d.reason AS decision_reason, d.decided_at
            FROM decisions d
            JOIN jobs j      ON j.id = d.job_id
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN matches m ON m.job_id = j.id
            ORDER BY d.decided_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ── CV ───────────────────────────────────────────────────────────────────────

def get_latest_cv():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cv ORDER BY uploaded_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def set_extra_keywords(cv_id: int, keywords: list[str]):
    with get_conn() as conn:
        conn.execute(
            "UPDATE cv SET extra_keywords_json=? WHERE id=?",
            (json.dumps(keywords), cv_id)
        )


def set_keyword_types(cv_id: int, types: dict[str, str]):
    """Store {skill: 'base'|'expert'} mapping for a CV."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE cv SET keyword_types_json=? WHERE id=?",
            (json.dumps(types), cv_id)
        )


def save_cv(raw_text: str, keywords: list[str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cv (raw_text, keywords_json) VALUES (?,?)",
            (raw_text, json.dumps(keywords))
        )
        return cur.lastrowid


# ── Matches ──────────────────────────────────────────────────────────────────

def save_match(job_id: int, score: int, reasoning: str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, is_override FROM matches WHERE job_id=?", (job_id,)
        ).fetchone()
        if existing and existing["is_override"]:
            return  # don't overwrite manual override
        if existing:
            conn.execute(
                "UPDATE matches SET match_score=?, reasoning=? WHERE job_id=?",
                (score, reasoning, job_id)
            )
        else:
            conn.execute(
                "INSERT INTO matches (job_id, match_score, reasoning) VALUES (?,?,?)",
                (job_id, score, reasoning)
            )


def set_match_override(job_id: int, override_score: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO matches (job_id, match_score, is_override, override_value)
            VALUES (?,?,1,?)
            ON CONFLICT(job_id) DO UPDATE SET
                is_override=1, override_value=excluded.override_value,
                match_score=excluded.match_score
        """, (job_id, override_score, override_score))


# ── Decisions ────────────────────────────────────────────────────────────────

def save_decision(job_id: int, decision: Optional[str], reason: Optional[str]):
    with get_conn() as conn:
        if decision is None:
            conn.execute("DELETE FROM decisions WHERE job_id=?", (job_id,))
        else:
            conn.execute("""
                INSERT INTO decisions (job_id, decision, reason, decided_at)
                VALUES (?,?,?,datetime('now'))
                ON CONFLICT(job_id) DO UPDATE SET
                    decision=excluded.decision,
                    reason=excluded.reason,
                    decided_at=excluded.decided_at
            """, (job_id, decision.lower(), reason))


# ── Scrape log ───────────────────────────────────────────────────────────────

def log_scrape(company_id: int, jobs_found: int, status: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scrape_log (company_id, jobs_found, status) VALUES (?,?,?)",
            (company_id, jobs_found, status)
        )
        return cur.lastrowid


def get_scrape_log(company_id: int, limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scrape_log WHERE company_id=? ORDER BY scraped_at DESC LIMIT ?",
            (company_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Settings ─────────────────────────────────────────────────────────────────

def ensure_settings_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        defaults = [
            ("match_threshold", "50"),
            ("scrape_time", "07:00"),
            ("report_day", "monday"),
            ("report_time", "08:00"),
            ("experience_level", "senior"),
            ("preferred_countries", "[]"),
        ]
        for k, v in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v)
            )


def get_setting(key: str, default: str = "") -> str:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default
    except Exception as e:
        logger.error("get_setting('%s') failed: %s", key, e)
        return default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            (key, value)
        )
