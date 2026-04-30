import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "talentbridge.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn):
    """Add columns introduced after initial schema."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(companies)")}
    for col, defn in [
        ("fetch",             "TEXT NOT NULL DEFAULT 'http'"),
        ("method",            "TEXT NOT NULL DEFAULT 'css'"),
        ("job_link_selector", "TEXT NOT NULL DEFAULT ''"),
        ("title_selector",    "TEXT NOT NULL DEFAULT ''"),
        ("pagination_json",   "TEXT NOT NULL DEFAULT '{}'"),
        ("api_body_json",     "TEXT NOT NULL DEFAULT '{}'"),
        ("job_base_url",      "TEXT NOT NULL DEFAULT ''"),
        ("portal_url",        "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {col} {defn}")

    jobs_existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "country" not in jobs_existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN country TEXT NOT NULL DEFAULT ''")
    if "posted_date" not in jobs_existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN posted_date TEXT")
    if "level_tag" not in jobs_existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN level_tag TEXT")
    if "profile_tags" not in jobs_existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN profile_tags TEXT NOT NULL DEFAULT '[]'")
    if "location_tags" not in jobs_existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN location_tags TEXT NOT NULL DEFAULT '[]'")

    cv_existing = {row[1] for row in conn.execute("PRAGMA table_info(cv)")}
    if "extra_keywords_json" not in cv_existing:
        conn.execute("ALTER TABLE cv ADD COLUMN extra_keywords_json TEXT NOT NULL DEFAULT '[]'")
    if "keyword_types_json" not in cv_existing:
        # Maps skill name → "base" | "expert". Default all existing skills to "expert".
        conn.execute("ALTER TABLE cv ADD COLUMN keyword_types_json TEXT NOT NULL DEFAULT '{}'")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_clusters (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT NOT NULL UNIQUE,
            skills_json      TEXT NOT NULL DEFAULT '[]',
            domain_tags_json TEXT NOT NULL DEFAULT '[]',
            skill_count      INTEGER NOT NULL DEFAULT 0,
            built_at         TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT NOT NULL,
            url                TEXT NOT NULL,
            fetch              TEXT NOT NULL DEFAULT 'http',
            method             TEXT NOT NULL DEFAULT 'css',
            job_link_selector  TEXT NOT NULL DEFAULT '',
            title_selector     TEXT NOT NULL DEFAULT '',
            pagination_json    TEXT NOT NULL DEFAULT '{}',
            api_body_json      TEXT NOT NULL DEFAULT '{}',
            job_base_url       TEXT NOT NULL DEFAULT '',
            portal_url         TEXT NOT NULL DEFAULT '',
            added_date         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL REFERENCES companies(id),
            title       TEXT NOT NULL,
            description TEXT,
            url         TEXT,
            location    TEXT,
            first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
            posted_date TEXT,
            is_expired  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS cv (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text      TEXT NOT NULL,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS matches (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id         INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
            match_score    INTEGER NOT NULL DEFAULT 0,
            reasoning      TEXT,
            is_override    INTEGER NOT NULL DEFAULT 0,
            override_value INTEGER
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      INTEGER NOT NULL REFERENCES jobs(id) UNIQUE,
            decision    TEXT NOT NULL CHECK(decision IN ('interested','applied','skipped')),
            reason      TEXT,
            decided_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL REFERENCES companies(id),
            scraped_at  TEXT NOT NULL DEFAULT (datetime('now')),
            jobs_found  INTEGER NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('success','rate_limited','failed','pending'))
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
        CREATE INDEX IF NOT EXISTS idx_matches_job  ON matches(job_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_job ON decisions(job_id);
        CREATE INDEX IF NOT EXISTS idx_scrape_company ON scrape_log(company_id);
        """)
        _migrate(conn)
