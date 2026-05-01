# TalentBridge

A locally-run, browser-based job tracking and matching tool. You upload your CV once — TalentBridge scrapes configured company career portals daily, scores each job against your profile, and keeps everything in one place. No accounts, no cloud, no login. It opens like a local web app in your browser.

> Built on FastAPI + SQLite + Jinja2, running entirely on localhost.

---

## How to Use

1. **First launch** — configure your Groq API key, SMTP email, and upload your CV. This is a one-time setup.
2. **Daily** — TalentBridge scrapes all configured companies automatically and matches new jobs to your CV.
3. **Browse** — open the dashboard to see matched jobs by company, filter, read descriptions, and set decisions.
4. **Email** — receive a daily digest of new matches and a weekly report every Monday morning.

---

## Features

### Companies View
Browse all configured companies as cards or a flat job list. Each company shows active job count, matched job count, and last scrape time. Filter jobs by level (Associate / Mid Level / Senior / Management / etc.), profile domain, and location — all filters are tag-based and update instantly.

> Tags (level, profile, location) are pre-computed after each scrape and stored in SQLite; filtering is a simple lookup with no keyword scanning at runtime.

### Company Detail
Click any company to see its full job list. Switch between All / Matched / Unmatched / Expired tabs instantly without a page reload. Click any job to open a side panel with the full description, skill match breakdown, and a direct link to the posting.

> Tab switching is pure JS; job descriptions are fetched lazily on demand and cached in-browser to keep the initial page load fast.

### Job Matching
Each job is scored 0–100% against your CV keywords. Jobs above the configured threshold (default 50%) are "matched." The match panel shows which skills were found, which were missing, and a short reasoning note. You can manually override any score.

> Matching uses the Groq API; keyword tiers (base vs. expert) weight the score.

### Decisions & Application Tracker
Mark any job as **Interested**, **Applied**, or **Skipped** (with a reason). The Application Tracker gives a cross-company view of all your decisions, filterable by status.

> Decisions are stored in SQLite and shown inline on both the company detail page and the tracker.

### CV Manager
Upload your CV (PDF or plain text) at any time. TalentBridge extracts skills and keywords, displays them grouped by cluster, and uses them for all future matching.

> Skill extraction and clustering use the Groq API; clusters are stored and browsable in the Skill Taxonomy screen.

### Weekly Report
A full HTML digest of the current calendar week: new jobs, matched jobs, jobs you applied to or skipped, and jobs that expired. Available in-app and sent by email every Monday. Previous weeks are accessible from the sidebar.

> Report data is scoped to ISO calendar week boundaries (Mon–Sun UTC) and generated from SQLite queries.

### Daily Match Email
Sent automatically each morning after the scrape completes — only if there are new matched jobs. Contains job title, company, score, and a direct link.

> Triggered by APScheduler running in the background process.

### Settings
Update your Groq API key, SMTP config, recipient email, scrape time, report day/time, and match threshold at any time from the Settings screen.

### Scheduled Scraping
Scrapes run daily at a configurable time (default 07:00). Each company's scrape status (success / failed / rate-limited) is logged and visible on the company card.

> APScheduler manages the schedule; Playwright handles JS-rendered career pages.
