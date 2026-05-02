# TalentBridge — Architecture

## 0. File & Folder Structure

```
TalentBridge/
│
├── run.py                        # Launch entry point — starts uvicorn on main.py
├── build.spec                    # PyInstaller spec for single-executable build
├── requirements.txt              # Python dependencies
├── partners.json                 # Operator config: all company scraper definitions
├── smtp_config.json              # Operator config: SMTP credentials
├── .env                          # User config: GROQ_API_KEY, REPORT_RECIPIENT
├── .env.example                  # Template for .env
│
├── backend/                      # All server-side logic
│   ├── main.py                   # App init & wiring — calls everyone once at startup
│   ├── api.py                    # FastAPI routes — the HTTP surface of the whole app
│   ├── db.py                     # SQLite connection, schema creation, migrations
│   ├── models.py                 # All DB queries — thin layer above db.py
│   ├── config.py                 # Loads partners.json → upserts companies into DB
│   ├── scraper.py                # Fetches jobs from career sites (CSS/Workday/Playwright)
│   ├── tagger.py                 # Heuristic tagging: level_tag, profile_tags, location_tags
│   ├── matcher.py                # Matching pipeline: scores all unmatched jobs vs CV
│   ├── heuristic_match.py        # Pure scoring function: keyword hits → 0–100 score
│   ├── llm.py                    # Groq API wrapper: CV extraction, taxonomy building
│   ├── skill_taxonomy.py         # Builds & clusters skill taxonomy from job descriptions
│   ├── geo.py                    # City → country lookup via geonamescache
│   ├── email_report.py           # Generates & sends daily/weekly/alert emails via SMTP
│   ├── scheduler.py              # APScheduler: daily scrape, matching, weekly report
│   ├── service.py                # OS startup registration (Windows/macOS/Linux)
│   ├── tray.py                   # pystray system tray icon & menu
│   └── __init__.py
│
├── frontend/
│   ├── templates/                # Jinja2 HTML templates (rendered server-side)
│   │   ├── base.html             # Shared layout, sidebar nav, console log panel
│   │   ├── companies.html        # Main screen: company cards + flat jobs view
│   │   ├── company_detail.html   # Per-company job list with tabs & side panel
│   │   ├── cv.html               # CV upload, keyword management, skill tiers
│   │   ├── tracker.html          # Cross-company application decision tracker
│   │   ├── report.html           # Weekly report viewer (per ISO calendar week)
│   │   ├── alerts.html           # Settings: SMTP recipient, schedule, threshold
│   │   └── jobs.html             # Redirect shim to /companies?view=jobs
│   └── static/
│       ├── css/                  # Stylesheets
│       └── js/                   # Shared JS utilities
│
├── data/                         # Runtime data — gitignored
│   ├── talentbridge.db           # SQLite database (all app state)
│   ├── talentbridge.db-shm       # SQLite WAL shared memory
│   ├── talentbridge.db-wal       # SQLite WAL write-ahead log
│   ├── skills_dump.json          # Debug export of extracted skills
│   └── logs/
│       └── console_*.txt         # Rolling log files (2000 lines each)
│
├── scripts/                      # One-off maintenance scripts (not part of app)
│   ├── clean_taxonomy.py         # Prune/deduplicate skill taxonomy in DB
│   └── cluster_skills.py         # Re-run clustering on existing taxonomy
│
└── project/                      # UI design reference (not served by app)
    ├── TalentBridge.html         # Static HTML mockup used during design phase
    ├── tb-data.js                # Sample data for mockup
    ├── tb-screens.jsx            # React component sketches
    └── tweaks-panel.jsx          # Design tweak panel
```

---

## 0.1 Backend Module Interactions

Each row is one file. Interactions are listed as `→ target (purpose)`.

| File | What it does | Interacts with |
|---|---|---|
| **main.py** | Initialises everything and starts uvicorn | → `db` (create schema) · → `models` (ensure settings table) · → `config` (load partners) · → `scheduler` (start cron jobs) · → `api` (mount FastAPI app) · → `tray` (system tray icon) · → `service` (OS startup registration) |
| **api.py** | All HTTP routes — the only public interface | → `models` (read/write all data) · → `scraper` (trigger scrape & desc fetch) · → `matcher` (trigger matching) · → `llm` (CV keyword extraction) · → `skill_taxonomy` (build & query taxonomy) · → `email_report` (send report on demand) · → `scheduler` (reschedule on settings save) |
| **db.py** | Opens SQLite connection, creates tables, runs migrations | ← used by `models`, `tagger`, `skill_taxonomy`, `geo` (raw connection only) |
| **models.py** | Every SQL query in one place — companies, jobs, CV, matches, decisions, scrape log, settings | → `db` (get connection) · ← called by `api`, `scraper`, `matcher`, `email_report`, `config`, `scheduler` |
| **config.py** | Reads `partners.json` and upserts company rows on startup | → `models` (upsert_company) |
| **scraper.py** | Fetches job listings from career sites using CSS selectors, Workday API, or Playwright | → `models` (upsert_job, mark_expired, log_scrape) · → `tagger` (tag after scrape & desc fetch) · → `geo` (extract location from description) · → `llm` (LLMRateLimitError only — no AI scraping) · → `email_report` (failure alert) |
| **tagger.py** | Pre-computes `level_tag`, `profile_tags`, `location_tags` for every untagged job | → `db` (read untagged jobs, write tags) |
| **matcher.py** | Runs heuristic scoring on all unmatched active jobs against the current CV | → `models` (get CV, get jobs, save matches) · → `heuristic_match` (score each job) · → `skill_taxonomy` (get skill list for gap detection) |
| **heuristic_match.py** | Pure function: keyword hits in job description → score 0–100 + detail breakdown | ← called only by `matcher` |
| **llm.py** | Wraps Groq API: sends prompts, handles rate limits, parses JSON responses | → Groq API (HTTPS) · ← called by `api` (CV extraction), `skill_taxonomy` (taxonomy + clustering) |
| **skill_taxonomy.py** | Builds a skill list from job descriptions (LLM-assisted), then clusters into domains | → `llm` (extract & cluster skills) · → `models` (read settings) · → `db` (write skill_clusters) |
| **geo.py** | Maps city names to countries; extracts city mentions from job descriptions | → `geonamescache` (bundled offline lookup) · ← called by `scraper` (during description fetch) |
| **email_report.py** | Builds HTML emails (daily matches, weekly digest, scrape failure alerts) and sends via SMTP | → `models` (query jobs, matches, decisions for report data) · → `db` (direct queries for weekly report) · → SMTP server (smtplib + STARTTLS) |
| **scheduler.py** | Registers and runs cron jobs in a background thread | → `scraper` (daily scrape) · → `matcher` (daily matching) · → `email_report` (weekly report + daily matches) · → `models` (read schedule settings) |
| **service.py** | Registers app in OS startup (Windows registry / macOS launchd / Linux systemd) | ← called once by `main` at startup |
| **tray.py** | Renders system tray icon with menu (Open Dashboard, Run Scrape, Quit) | → `api` (HTTP calls to trigger scrape) · ← called once by `main` |

---

## 0.2 Frontend Template Interactions

| Template | Screen | Key API calls |
|---|---|---|
| **base.html** | Shared layout — sidebar, console log, status badge | `GET /api/status` (poll) · `GET /api/console/stream` (SSE) |
| **companies.html** | Company cards + flat jobs list, filters, search | `GET /api/status` · `POST /api/scrape/now` · `POST /api/descriptions/fetch` · `GET /api/descriptions/status` · `GET /api/jobs/search` · `POST /api/decisions/{id}` |
| **company_detail.html** | Per-company jobs with All/Matched/Expired tabs | `GET /api/jobs/{id}` (lazy desc fetch) · `POST /api/decisions/{id}` · `POST /api/matches/{id}/override` |
| **cv.html** | CV upload, keyword tiers, match trigger | `POST /cv/upload` · `POST /cv/keywords` · `POST /cv/keyword-types` · `POST /api/match/now` · `GET /api/match/status` · `GET /api/taxonomy/status` · `POST /api/taxonomy/build` · `GET /api/taxonomy/clusters` · `GET/POST /api/experience-level` · `GET/POST /api/preferred-countries` |
| **tracker.html** | Application decisions (Interested / Applied / Skipped) | `POST /api/decisions/{id}` · `DELETE /api/decisions/{id}` |
| **report.html** | Weekly digest viewer, per ISO calendar week | `GET /api/report/weeks` · `POST /report/send` |
| **alerts.html** | Schedule & email settings form | `POST /alerts` (form submit) |

---

## Overview

TalentBridge runs entirely on localhost. A FastAPI process serves the dashboard, runs a background scheduler, and talks to a single SQLite database. No cloud, no accounts, no shared state. Each user runs their own instance.

---

## 1. Static Module Structure

```mermaid
graph TD
    main["main.py\nEntrypoint & init"]

    subgraph Core
        api["api.py\nFastAPI routes"]
        scheduler["scheduler.py\nAPScheduler"]
        db["db.py\nSQLite connection & schema"]
        models["models.py\nQuery helpers"]
    end

    subgraph Processing
        scraper["scraper.py\nMulti-method scraper"]
        tagger["tagger.py\nHeuristic job tagging"]
        matcher["matcher.py\nMatching pipeline"]
        heuristic["heuristic_match.py\nKeyword scoring"]
        geo["geo.py\nCity→country lookup"]
    end

    subgraph AI
        llm["llm.py\nGroq API wrapper"]
        taxonomy["skill_taxonomy.py\nTaxonomy & clustering"]
    end

    subgraph Output
        email["email_report.py\nReport generation & SMTP"]
    end

    subgraph Bootstrap
        config["config.py\nLoad partners.json"]
        service["service.py\nOS startup registration"]
        tray["tray.py\npystray system tray"]
    end

    main --> db
    main --> models
    main --> config
    main --> scheduler
    main --> api
    main --> tray
    main --> service

    api --> models
    api --> scraper
    api --> matcher
    api --> taxonomy
    api --> llm
    api --> email

    scheduler --> scraper
    scheduler --> matcher
    scheduler --> email

    scraper --> models
    scraper --> geo
    scraper --> tagger
    scraper --> llm

    matcher --> models
    matcher --> heuristic
    matcher --> taxonomy

    taxonomy --> llm
    taxonomy --> models

    tagger --> db
    models --> db
    email --> models
    geo --> db
    config --> models
```

---

## 2. Database Schema

```mermaid
erDiagram
    companies {
        int     id              PK
        text    name
        text    url
        text    fetch
        text    method
        text    job_link_selector
        text    title_selector
        text    pagination_json
        text    api_body_json
        text    job_base_url
        text    portal_url
        text    added_date
    }

    jobs {
        int     id              PK
        int     company_id      FK
        text    title
        text    description
        text    url
        text    location
        text    country
        text    first_seen
        text    last_seen
        text    posted_date
        int     is_expired
        text    expired_at
        text    level_tag
        text    profile_tags
        text    location_tags
    }

    matches {
        int     id              PK
        int     job_id          FK
        int     match_score
        text    reasoning
        int     is_override
        int     override_value
    }

    decisions {
        int     id              PK
        int     job_id          FK
        text    decision
        text    reason
        text    decided_at
    }

    cv {
        int     id              PK
        text    raw_text
        text    keywords_json
        text    extra_keywords_json
        text    keyword_types_json
        text    uploaded_at
    }

    scrape_log {
        int     id              PK
        int     company_id      FK
        text    scraped_at
        int     jobs_found
        text    status
    }

    skill_clusters {
        int     id              PK
        text    name
        text    skills_json
        text    domain_tags_json
        int     skill_count
        text    built_at
    }

    settings {
        text    key             PK
        text    value
    }

    companies ||--o{ jobs : "has"
    companies ||--o{ scrape_log : "logged in"
    jobs ||--o| matches : "scored by"
    jobs ||--o| decisions : "decided by"
```

---

## 3. Data Flow — Daily Scrape Cycle

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant SC as scraper.py
    participant DB as SQLite
    participant GEO as geo.py
    participant TAG as tagger.py
    participant EXT as Career Sites

    S->>SC: run_scrape() at 07:00
    loop each company
        SC->>EXT: HTTP/Playwright fetch
        EXT-->>SC: HTML / JSON
        SC->>SC: parse (CSS / Workday / JSON embed)
        SC->>DB: upsert_job() per title
        SC->>DB: mark_expired_jobs()
        SC->>DB: log_scrape(status)
        SC->>TAG: tag_untagged_jobs() — sync
        SC-->>SC: spawn _fetch_all_descriptions() async
    end

    Note over SC: Background task (non-blocking)
    loop each job without description
        SC->>EXT: fetch job URL
        EXT-->>SC: HTML
        SC->>GEO: extract_location_from_description()
        GEO-->>SC: city, country
        SC->>DB: update jobs (description, location, country)
        SC->>TAG: tag_untagged_jobs() — re-tag with desc
    end
```

---

## 4. Data Flow — Job Matching

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant M as matcher.py
    participant HM as heuristic_match.py
    participant TX as skill_taxonomy.py
    participant DB as SQLite
    participant ER as email_report.py
    participant SMTP as SMTP Server

    S->>M: run_matching() at 08:00
    M->>DB: get_latest_cv() → keywords + tiers
    M->>TX: get_taxonomy() → skill list
    M->>DB: get unmatched active jobs
    loop each job
        M->>HM: heuristic_score(desc, base_kws, expert_kws)
        Note over HM: Check exp level exclusions<br/>Check preferred countries<br/>Score base+expert hits
        HM-->>M: (score 0-100, detail)
        M->>DB: save_match(job_id, score, reasoning)
    end
    M->>ER: send_daily_matches() if new matches ≥ threshold
    ER->>SMTP: send HTML email
```

---

## 5. Data Flow — CV Upload & Keyword Extraction

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant API as api.py
    participant DB as SQLite
    participant LLM as llm.py
    participant GROQ as Groq API

    U->>API: POST /cv/upload (PDF or text)
    API->>API: extract text (pypdf or raw)
    API->>DB: save_cv(raw_text, [])
    API-->>U: {ok, cv_id} — responds immediately

    Note over API,GROQ: Async extraction (non-blocking)
    API->>LLM: extract_cv_keywords(cv_text)
    loop per 12k-char chunk
        LLM->>GROQ: POST /chat/completions
        GROQ-->>LLM: JSON array of skills
    end
    LLM-->>API: deduplicated skill list
    API->>DB: UPDATE cv SET keywords_json

    U->>API: POST /cv/keyword-types (base/expert tiers)
    API->>DB: set_keyword_types(cv_id, {skill: tier})
```

---

## 6. Data Flow — Skill Taxonomy Build

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant API as api.py
    participant TX as skill_taxonomy.py
    participant LLM as llm.py
    participant GROQ as Groq API
    participant DB as SQLite

    U->>API: POST /api/taxonomy/build
    API-->>U: {ok} — background task spawned

    Note over TX,GROQ: Phase 1 — Extract skills from job descriptions
    TX->>DB: get job descriptions
    TX->>LLM: seed with first job description
    LLM->>GROQ: POST /chat/completions
    GROQ-->>LLM: skill list
    loop each remaining job
        TX->>TX: heuristic hit rate check
        alt hit_rate < 20%
            TX->>LLM: extract new skills
            LLM->>GROQ: POST /chat/completions
            GROQ-->>LLM: new skills
            TX->>TX: merge into taxonomy
        end
    end
    TX->>DB: save skill_taxonomy_json to settings

    Note over TX,GROQ: Phase 2 — Cluster into domains
    loop batches of 150 skills
        TX->>LLM: cluster batch
        LLM->>GROQ: POST /chat/completions
        GROQ-->>LLM: [{name, skills, domain_tags}]
        TX->>TX: merge clusters
    end
    TX->>DB: INSERT skill_clusters
```

---

## 7. Data Flow — Weekly Report

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant ER as email_report.py
    participant DB as SQLite
    participant SMTP as SMTP Server
    participant U as User Email Client

    S->>ER: send_weekly_report() on Monday 08:00
    ER->>DB: query jobs WHERE first_seen in ISO week
    ER->>DB: query matches (≥ threshold)
    ER->>DB: query decisions (applied, skipped, interested)
    ER->>DB: query jobs WHERE expired_at in ISO week
    ER->>ER: build_weekly_report_data() → dict
    ER->>ER: render HTML email (inline styles)
    ER->>SMTP: send via smtplib (starttls)
    SMTP-->>U: HTML digest email
```

---

## 8. External Interfaces

```mermaid
graph LR
    subgraph TalentBridge ["TalentBridge (localhost)"]
        LLM["llm.py"]
        SCRAPER["scraper.py"]
        EMAIL["email_report.py"]
        GEO["geo.py"]
    end

    subgraph External
        GROQ["Groq API\napi.groq.com\nllama-3.3-70b-versatile"]
        SITES["Career Sites\n(50+ company portals)"]
        SMTP["SMTP Server\nGmail / custom"]
        GEONAMES["geonamescache\n(bundled, offline)"]
    end

    LLM -->|"POST /chat/completions\nBearer GROQ_API_KEY"| GROQ
    SCRAPER -->|"HTTP GET / Playwright\nChrome UA"| SITES
    EMAIL -->|"SMTP + STARTTLS :587\nsmtp_config.json credentials"| SMTP
    GEO -->|"city→country lookup\nbundled package"| GEONAMES
```

| Interface | Protocol | Auth | Used For |
|---|---|---|---|
| Groq API | HTTPS / OpenAI-compat | `GROQ_API_KEY` in `.env` | CV extraction, taxonomy building |
| Career Sites | HTTP / Playwright | None (public) | Job scraping |
| SMTP | STARTTLS :587 | `smtp_config.json` | Daily + weekly email reports |
| geonamescache | Python package (offline) | None | City → country resolution |

---

## 9. Threading & Concurrency Model

```mermaid
graph TD
    subgraph Main Thread
        UV["uvicorn ASGI server\n(async event loop)"]
    end

    subgraph Daemon Threads
        SCH["APScheduler\nBackgroundScheduler"]
        TRAY["pystray\nsystem tray"]
        BROWSER["webbrowser.open\n(one-shot)"]
    end

    subgraph Async Tasks on Main Loop
        SCRAPE["run_scrape()\n_scrape_lock"]
        MATCH["run_matching()\n_match_lock"]
        DESC["_fetch_all_descriptions()\nfire-and-forget"]
        TAXO["build_taxonomy()\nBackground FastAPI task"]
    end

    SCH -->|"_run_async(coro)\nnew event loop per job"| SCRAPE
    SCH -->|"_run_async(coro)"| MATCH
    UV -->|"asyncio.create_task()"| DESC
    UV -->|"BackgroundTasks"| TAXO
```

**Key concurrency rules:**
- `_scrape_lock` — prevents concurrent scrape runs
- `_match_lock` — prevents concurrent match runs
- Description fetch is fire-and-forget; scheduler drains all pending tasks before closing its isolated loop
- Scheduler creates a **new event loop per job** (`_run_async`) to avoid cross-thread loop conflicts

---

## 10. Scraper Method Decision Tree

```mermaid
flowchart TD
    A[company config] --> B{fetch type}
    B -->|api| C{method}
    B -->|http| D{method}

    C -->|workday| E[POST Workday JSON API\npaginated offset/limit]
    C -->|paginated_json_embed| F[GET page → extract\nscript JSON embed]

    D -->|css| G{JS required?}
    D -->|paginated_css| H[Loop ?page=N\nstop on no new titles]

    G -->|known SSR\nGreenhouse/Lever/Ashby| I[httpx GET\nBeautifulSoup CSS selectors]
    G -->|JS-rendered| J[Playwright headless Chrome\nscroll + wait]

    I --> K[parse job_link_selector\ntitle_selector]
    J --> K
    H --> K
    E --> L[normalize titles + URLs]
    F --> L
    K --> L
    L --> M[upsert_job per title]
```

---

## 11. Job Tagging Logic

Tags are pre-computed once after scrape/description fetch and stored in the DB. Filtering is a simple tag lookup — no keyword scanning at runtime.

```mermaid
flowchart TD
    T[job title + description] --> L[Level Tag\nsingle value]
    T --> P[Profile Tags\nmulti-value list]
    T --> LOC[Location Tags\nmulti-value list]

    L --> L1{priority order}
    L1 -->|tech lead / manager / director| MGT[Management]
    L1 -->|intern / ausbildung| STU[Student Jobs]
    L1 -->|entry level| ENT[Entry]
    L1 -->|associate / junior| ASC[Associate]
    L1 -->|senior / principal / staff| SEN[Senior]
    L1 -->|developer / engineer\nAND no senior signals| MID[Mid Level]
    L1 -->|fallback| OTH[Others]

    P --> P1[Match title + description\nagainst domain keyword sets]
    P1 --> P2["[Software Developer,\nDevOps, Data/ML, ...]"]

    LOC --> LOC1[Split on , / | ; and/or]
    LOC1 --> LOC2[Normalize: Remote / Hybrid]
    LOC1 --> LOC3[Match cities via geonamescache]
    LOC2 & LOC3 --> LOC4["[Munich, Remote, ...]"]
```

---

## 12. Heuristic Matching Score

```mermaid
flowchart TD
    IN["job description\n+ CV keywords (base + expert)\n+ user exp level\n+ preferred countries"] --> EX{Exclusion checks}

    EX -->|job title matches excluded level| Z[score = 0]
    EX -->|job country not in preferred list| Z
    EX -->|no description or < 20 chars| Z

    EX -->|pass| HITS[Find keyword hits\nin description]
    HITS --> BASE{base keywords\ndefined?}

    BASE -->|yes, hits found| S1["50 + (expert_hits × 5)\ncapped at 100"]
    BASE -->|yes, no hits| S2["expert_hits × 3\n(weak match)"]
    BASE -->|no base defined| S3["expert_hits × 10"]

    S1 & S2 & S3 --> OUT["(score, detail)\ndetail = {matched_base, matched_expert,\nmissing, score_note}"]
```

---

## 13. Configuration Files

| File | Managed By | Purpose |
|---|---|---|
| `.env` | User / operator | `GROQ_API_KEY`, `REPORT_RECIPIENT` |
| `smtp_config.json` | Operator | SMTP host, port, user, password |
| `partners.json` | Operator | All company scraper configs |
| `data/talentbridge.db` | App | All runtime data |
| `data/logs/console_*.txt` | App | Rolling log files (2000 lines each) |

Settings that users can change at runtime (scrape time, threshold, report schedule, preferred countries, experience level) are stored in the `settings` table and editable via the dashboard.
