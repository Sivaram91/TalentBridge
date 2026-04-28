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


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            url         TEXT NOT NULL,
            added_date  TEXT NOT NULL DEFAULT (datetime('now'))
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
