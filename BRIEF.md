# TalentBridge — Project Brief

## What It Is

A locally-run, browser-based job tracking and matching tool for outplacement support.
Employees upload their CV once. The tool scrapes ~50 pre-configured partner company
career portals daily, matches job listings against the CV using AI, and sends a weekly
HTML email digest summarizing activity.

No hosting. No accounts. No login. Opens like a local web app in the browser (similar
to how Jupyter Notebook works).

---

## Core Principles

- **KISS** — Keep It Simple. Every screen does one thing well.
- **Local-first** — All data stored in SQLite on the user's machine. No cloud sync.
- **AI-assisted** — Use AI for both job extraction from heterogeneous HTML and CV matching.
- **Offline-capable** — Ollama (local LLM) as fallback when no internet/API available.

---

## Users

Small group of employees (not thousands). Each employee runs their own instance.
No shared accounts, no multi-user setup.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python | Scraping, scheduling, email, AI calls |
| Scraping | Playwright | Handles JS-heavy career pages |
| Scheduling | APScheduler | Daily scrape + weekly report, runs in background service |
| AI | Gemini free tier API | User provides their own API key on first launch |
| Storage | SQLite | Single file, no setup needed |
| Local API | FastAPI on localhost | Serves dashboard, exposes REST endpoints for UI |
| Frontend | Browser-based (HTML/JS served by FastAPI) | Opens on localhost via system tray |
| Email | smtplib | User provides their own SMTP config on first launch |
| System tray | pystray | Background service icon, start/stop, open dashboard |
| Installer | PyInstaller | Bundles everything into a single executable |

---

## Background Service

The app runs as a persistent background service, not a manually launched script.

- Starts automatically with OS on every boot
  - Windows: registered as a Windows Service or startup entry
  - Mac: launchd plist in `~/Library/LaunchAgents`
  - Linux: systemd user service
- System tray icon always visible — right-click menu:
  - Open Dashboard
  - Run Scrape Now
  - Pause / Resume
  - Quit
- Closing the browser dashboard does nothing — service keeps running
- All scheduled tasks (daily scrape, matching, emails) run via APScheduler inside the service
- FastAPI serves the dashboard on `localhost:7070` (configurable port)

---

## First Launch Experience

On first run, before anything else, user is guided through a one-time setup screen in the browser:

1. **Gemini API key** — input field, link to Google AI Studio to get the key
2. **Email configuration** — sender address, SMTP host/port, app password, recipient address
3. **CV upload** — PDF or plain text
4. **Scrape time preference** — default 07:00

Once saved, setup never appears again. All values stored in `.env` locally. User can revisit via Settings screen in dashboard.

---

### 1. Company Overview (Home Screen)

- Grid or list of all ~50 partner companies (pre-seeded in config)
- Per company card shows:
  - Company name
  - Total **active** job listings scraped
  - Number of **matched** jobs (match score > 50%, active only)
  - Last scraped timestamp
- Expired jobs are **excluded** from all counts
- Clicking a company card navigates to Per-Company View

---

### 2. Per-Company View

- Lists **all** job listings for that company, displayed inside the tool
- "Visit Career Portal" button — opens company's career page in a new browser tab
- Per job listing shows:
  - Job title
  - Match score (%)
  - Short AI reasoning snippet (why it matches or doesn't)
  - Status badge: **Active** or **Expired**
  - User decision badge: **Interested** / **Applied** / **Skipped** (with reason)
  - "View Job" link — direct URL to the job listing (if available)
- Filter bar: **All / Matched / Unmatched / Expired**
- Expired jobs are visually de-emphasized (greyed out) but still visible unless filtered out
- User can manually **override** the AI's match decision
- User can set decision on any job: Interested / Applied / Skipped + free-text reason

---

### 3. CV Manager

- Upload CV once (PDF or plain text)
- Tool extracts and displays the keywords it found
- Shows when CV was last updated
- Replace CV at any time — re-runs matching on next scrape cycle

---

### 4. Application Tracker

- Cross-company view of all jobs where user has set a decision
- Shows: job title, company, match score, decision, reason (for Skipped)
- Filterable by decision type: Interested / Applied / Skipped
- Clickable job titles link to original job URLs

---

### 5. Weekly Report (HTML Email)

- Sent every Monday morning (configurable)
- Sections:
  - New jobs posted this week
  - Jobs matching your profile (score > 50%)
  - Jobs you marked as Interested
  - Jobs you Applied to
  - Jobs you Skipped (with reasons)
- All job titles are clickable links to actual job URLs
- In-app preview available before send

### 6. Settings Screen

Accessible anytime from sidebar. Allows user to update:
- Gemini API key
- Email configuration (SMTP, recipient)
- Scrape time preference
- Match threshold (default 50%)
- CV (same as CV Manager, linked)

---

- Partner company URLs are **pre-seeded** in a config file (`partners.json`)
- Scraper runs daily at configurable time (default: 07:00 local time)
- Uses Playwright to handle JS-rendered pages
- AI (Gemini) extracts structured data from raw HTML: title, description, URL, location
- Jobs not found in latest scrape are marked **Expired** (not deleted)
- No deduplication required in v1 — keep it simple

### Rate Limit Handling

- Gemini free tier rate limits are respected via a **scrape queue**
- If a Gemini API call hits a rate limit (429 response):
  - That company is pushed back into a **pending queue**
  - Scraper pauses, waits for the rate limit window to expire (exponential backoff)
  - Resumes processing the queue automatically
- Daily scrape is considered complete only when all companies are processed (or explicitly failed after max retries)
- Scrape log records per-company status: `success`, `rate_limited`, `failed`, `pending`
- Dashboard shows per-company scrape status so user can see what's still in queue

---

## Matching Logic

- CV keywords extracted by AI on upload
- Each job description scored against CV keywords
- Match score: 0–100% (jobs above 50% are "matched")
- AI also generates a short reasoning snippet per job
- User can manually override any AI match decision

---

## Email Configuration

- SMTP settings configured in `.env` file
- Recipient email address pre-configured (not entered per send)
- Weekly send on Monday 08:00 (configurable)
- HTML format with inline styles (works in all email clients)
- Clickable links to job URLs and company portals

---

## Data Storage (SQLite Schema — simplified)

```
companies       — id, name, url, added_date
jobs            — id, company_id, title, description, url, location, first_seen, last_seen, is_expired
cv              — id, raw_text, keywords_json, uploaded_at
matches         — id, job_id, match_score, reasoning, is_override, override_value
decisions       — id, job_id, decision (interested/applied/skipped), reason, decided_at
scrape_log      — id, company_id, scraped_at, jobs_found, status
```

---

## Configuration Files

### `partners.json` — pre-seeded partner companies
```json
[
  { "name": "Infineon Technologies", "url": "https://infineon.com/careers" },
  { "name": "Continental AG", "url": "https://continental.com/careers" }
]
```

### `.env` — secrets and settings
```
GEMINI_API_KEY=your_key_here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASS=your_app_password
REPORT_RECIPIENT=your@email.com
SCRAPE_TIME=07:00
REPORT_DAY=monday
REPORT_TIME=08:00
MATCH_THRESHOLD=50
```

---

## Project Structure

```
talentbridge/
├── BRIEF.md                  # This file
├── TalentBridge.html         # Reference design from Claude design
├── .env                      # Config and secrets (gitignored)
├── partners.json             # Pre-seeded partner company URLs
├── data/
│   └── talentbridge.db       # SQLite database
├── backend/
│   ├── main.py               # Entry point — starts FastAPI + APScheduler + pystray
│   ├── service.py            # OS startup registration (Windows/Mac/Linux)
│   ├── tray.py               # System tray icon and menu (pystray)
│   ├── scraper.py            # Playwright scraping logic
│   ├── matcher.py            # Gemini matching logic
│   ├── scheduler.py          # APScheduler jobs (scrape, match, email)
│   ├── email_report.py       # HTML email generation and sending
│   └── gemini.py             # Gemini API calls with rate limit handling
├── frontend/
│   ├── templates/            # Jinja2 HTML templates (based on TalentBridge.html design)
│   └── static/               # CSS, JS
├── requirements.txt
└── build.spec                # PyInstaller spec for single executable
```

---

## Build Order (recommended for Claude Code sessions)

1. SQLite schema + data layer
2. FastAPI skeleton + localhost serving
3. First launch + settings screen
4. Partner config loading + Company Overview page
5. Playwright scraper + scrape log + rate limit queue
6. CV upload + keyword extraction
7. Gemini integration + rate limit handling
8. AI matching + match storage
9. Per-Company View with filters
10. Application Tracker (decisions)
11. Daily match email + weekly HTML report
12. System tray (pystray) + OS startup registration
13. PyInstaller build + single executable packaging

---

## Email Triggers

Three email types, all independent complete experiences — no need to open the dashboard to act on them.

### 1. Daily — New Matches (post-scrape)
- Triggered every morning after daily scrape completes
- Only sent if there are **new matching jobs** that day (no empty emails)
- Contains per matched job: title, company, match score, reasoning snippet, direct job URL
- Lightweight and scannable

### 2. Weekly — Full Activity Report (Monday morning)
- Comprehensive HTML digest covering the past 7 days
- Sections:
  - New jobs posted across all partner companies
  - Jobs matching your profile (score > 50%)
  - Jobs marked Interested / Applied / Skipped with reasons
  - Company-level summary (active listings, matched count per company)
- All job titles are clickable links to actual job URLs

### 3. Ad-hoc — Scrape Failure Alert
- Triggered only when a company **consistently fails** after all retries
- Distinct from rate limiting — covers actual failures (site down, structure changed)
- Brief alert: which company failed, how many consecutive days, last successful scrape date
- Not sent daily — only when something breaks

---

## Out of Scope (v1)

- Multi-user support
- Cloud hosting
- Job deduplication across scrape cycles
- Browser extension
- Mobile view
```
