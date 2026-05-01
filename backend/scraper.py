"""Deterministic scraper — CSS selectors, Workday API, paginated HTML. AI never used for scraping."""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _safe_task(coro, name: str = "task"):
    """create_task wrapper that logs exceptions instead of silently dropping them."""
    async def _run():
        try:
            await coro
        except Exception as exc:
            logger.error("Background task '%s' failed: %s", name, exc, exc_info=True)
    return asyncio.create_task(_run())


MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 300]

# ── Posted date extraction ────────────────────────────────────────────────────

_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

# Patterns tried in order — first match wins
_DATE_PATTERNS = [
    # ISO: 2024-11-25 or 2024/11/25
    (re.compile(r'\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b'), 'ymd'),
    # US: 11/25/2024 or 11-25-2024
    (re.compile(r'\b(0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])[-/](20\d{2})\b'), 'mdy'),
    # EU: 25.11.2024 or 25/11/2024
    (re.compile(r'\b(0?[1-9]|[12]\d|3[01])[./](0?[1-9]|1[0-2])[./](20\d{2})\b'), 'dmy'),
    # "25 November 2024" or "November 25, 2024" or "25 Nov 2024"
    (re.compile(r'\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(20\d{2})\b', re.I), 'dmy_text'),
    (re.compile(r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b', re.I), 'mdy_text'),
]

# Labels that must appear near the date for it to be considered a posted date
_POSTED_LABELS = re.compile(
    r'(posted|published|date posted|job posted|veröffentlicht|eingestellt am|created|listing date|date added|start date)\s*[:\-–]?\s*$',
    re.I
)

# Labels that indicate it's NOT a posted date (application deadline etc.)
_EXCLUDE_LABELS = re.compile(
    r'(deadline|apply by|closing date|expir|valid until|bewerbungsschluss)',
    re.I
)


def extract_posted_date(text: str) -> str | None:
    """
    Scan description text for a posting date.
    Returns ISO date string 'YYYY-MM-DD' or None.
    Only accepts dates that are plausibly a posted date (labelled or in first 500 chars).
    Rejects future dates and dates older than 2 years.
    """
    today = date.today()
    min_date = date(today.year - 2, today.month, today.day)

    lines = text.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _EXCLUDE_LABELS.search(stripped):
            continue

        for pattern, fmt in _DATE_PATTERNS:
            m = pattern.search(stripped)
            if not m:
                continue
            try:
                if fmt == 'ymd':
                    y, mo, d_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif fmt == 'mdy':
                    mo, d_, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif fmt == 'dmy':
                    d_, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif fmt == 'dmy_text':
                    d_, mo_str, y = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
                    mo = _MONTH_MAP.get(mo_str)
                    if not mo:
                        continue
                elif fmt == 'mdy_text':
                    mo_str, d_, y = m.group(1).lower()[:3], int(m.group(2)), int(m.group(3))
                    mo = _MONTH_MAP.get(mo_str)
                    if not mo:
                        continue
                else:
                    continue

                parsed = date(y, mo, d_)
            except ValueError:
                continue

            # Reject future dates and very old dates
            if parsed > today or parsed < min_date:
                continue

            # Accept if: line has a posted label, OR date is in the first 500 chars of text
            before = stripped[:m.start()]
            if _POSTED_LABELS.search(before) or text.find(stripped) < 500:
                return parsed.isoformat()

    return None

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_scrape_lock = asyncio.Lock()
_desc_semaphore = asyncio.Semaphore(5)
_desc_fetch_active  = 0    # number of companies currently having descriptions fetched
_desc_fetch_done    = 0    # jobs processed in current fetch run
_desc_fetch_total   = 0    # total jobs to process in current fetch run
_desc_fetch_current = ""   # URL currently being fetched (for display)
_desc_fetch_cancel  = False  # set True to abort the current fetch run
_scrape_started_at: float = 0.0


async def scrape_company(company: dict) -> Optional[list[dict]]:
    method = company.get("method") or "css"

    if method == "workday":
        return await _scrape_workday(company)
    elif method == "paginated_css":
        return await _scrape_paginated_css(company)
    elif method == "paginated_json_embed":
        return await _scrape_paginated_json_embed(company)
    else:
        return await _scrape_css(company)


# ── CSS scraper (single page) ────────────────────────────────────────────────

async def _scrape_css(company: dict) -> Optional[list[dict]]:
    selector = company.get("job_link_selector", "").strip()
    if not selector:
        logger.warning("No job_link_selector for %s — skipping", company["name"])
        return None
    fetch = company.get("fetch") or "http"
    html = await _fetch_http(company["url"]) if fetch == "http" else await _fetch_js(company["url"])
    if html is None:
        return None
    jobs = _parse_css(html, selector, company.get("title_selector", ""))
    logger.info("CSS extracted %d jobs from %s", len(jobs), company["name"])
    return jobs or None


# ── Paginated CSS scraper ────────────────────────────────────────────────────

async def _scrape_paginated_css(company: dict) -> Optional[list[dict]]:
    pagination = json.loads(company.get("pagination_json", "{}"))
    param = pagination.get("param", "page")
    step = pagination.get("step", 1)
    start = pagination.get("start", 1)
    selector = company.get("job_link_selector", "")
    title_sel = company.get("title_selector", "")
    base_url = company["url"]
    all_jobs: list[dict] = []
    seen_titles: set[str] = set()
    page = start

    MAX_PAGES = 200
    while page <= start + MAX_PAGES * step:
        url = f"{base_url}{'&' if '?' in base_url else '?'}{param}={page}"
        html = await _fetch_http(url)
        if not html:
            break
        jobs = _parse_css(html, selector, title_sel)
        new = [j for j in jobs if j["title"].lower() not in seen_titles]
        if not new:
            break
        for j in new:
            seen_titles.add(j["title"].lower())
        all_jobs.extend(new)
        logger.debug("Page %s: +%d jobs (%d total) from %s", page, len(new), len(all_jobs), company["name"])
        page += step
    else:
        logger.warning("Paginated CSS hit %d-page cap for %s", MAX_PAGES, company["name"])

    logger.info("Paginated CSS extracted %d jobs from %s", len(all_jobs), company["name"])
    return all_jobs or None


# ── Workday JSON API scraper ─────────────────────────────────────────────────

async def _scrape_workday(company: dict) -> Optional[list[dict]]:
    api_url = company["url"]
    base_body = json.loads(company.get("api_body_json", "{}"))
    job_base_url = company.get("job_base_url", "")
    limit = base_body.get("limit", 20)
    all_jobs: list[dict] = []
    offset = 0
    total = 0

    async with httpx.AsyncClient(timeout=30, headers=_HTTP_HEADERS) as client:
        while True:
            body = {**base_body, "limit": limit, "offset": offset}
            try:
                resp = await client.post(api_url, json=body, headers={"Content-Type": "application/json"})
                if resp.status_code != 200:
                    logger.warning("Workday API %s -> %d", api_url, resp.status_code)
                    break
                data = resp.json()
            except Exception as e:
                logger.warning("Workday API error for %s: %s", company["name"], e)
                break

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for p in postings:
                title = p.get("title", "").strip()
                path = p.get("externalPath", "")
                url = f"{job_base_url}{path}" if path else ""
                location = p.get("locationsText", "")
                if title:
                    all_jobs.append({"title": title, "url": url, "location": location, "description": ""})

            page_total = data.get("total", 0)
            if page_total:
                total = page_total
            offset += limit
            logger.debug("Workday offset %d/%d for %s", offset, total, company["name"])
            if total and offset >= total:
                break

    logger.info("Workday API extracted %d jobs from %s", len(all_jobs), company["name"])
    return all_jobs or None


async def _fetch_http(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HTTP_HEADERS) as client:
            resp = await client.get(url)
        return resp.text if resp.status_code == 200 else None
    except Exception as e:
        logger.warning("HTTP fetch failed %s: %s", url, e)
        return None


async def _scrape_paginated_json_embed(company: dict) -> Optional[list[dict]]:
    """Scrape sites that embed job data as a JS object in the page (e.g. ABB phApp.ddo)."""
    import re
    pagination = json.loads(company.get("pagination_json", "{}"))
    param = pagination.get("param", "from")
    step = pagination.get("step", 10)
    start = pagination.get("start", 0)
    base_url = company["url"]
    all_jobs: list[dict] = []
    seen: set[str] = set()
    offset = start

    while True:
        url = f"{base_url}{'&' if '?' in base_url else '?'}{param}={offset}"
        html = await _fetch_http(url)
        if not html:
            break

        # ABB/Phenom: eagerLoadRefineSearch.totalHits + eagerLoadRefineSearch.data.jobs
        total_m = re.search(r'"totalHits"\s*:\s*(\d+)', html)
        total = int(total_m.group(1)) if total_m else 0

        # Find start of jobs array using bracket counting (nested arrays inside jobs)
        marker = '"eagerLoadRefineSearch"'
        marker_pos = html.find(marker)
        if marker_pos < 0:
            break
        jobs_key = html.find('"jobs":[', marker_pos)
        if jobs_key < 0:
            break
        arr_start = jobs_key + len('"jobs":')
        depth, i, n = 0, arr_start, len(html)
        while i < n:
            if html[i] == '[':
                depth += 1
            elif html[i] == ']':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        try:
            jobs_data = json.loads(html[arr_start:i+1])
        except Exception:
            break

        if not jobs_data:
            break

        new = []
        for j in jobs_data:
            title = j.get("title", "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            job_id = j.get("jobId", "")
            url_path = j.get("applyUrl") or j.get("canonicalPositionUrl") or ""
            location = j.get("city", "") or j.get("country", "")
            new.append({"title": title, "url": url_path, "location": location, "description": ""})

        if not new:
            break
        all_jobs.extend(new)
        logger.debug("JSON-embed offset %d/%d: +%d jobs (%d total) from %s", offset, total, len(new), len(all_jobs), company["name"])
        offset += step
        if total and offset >= total:
            break

    logger.info("JSON-embed extracted %d jobs from %s", len(all_jobs), company["name"])
    return all_jobs or None


def _parse_css(html: str, job_link_selector: str, title_selector: str) -> list[dict]:
    """Parse job listings from HTML using explicit CSS selectors via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed — cannot use CSS selectors")
        return []

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()

    for el in soup.select(job_link_selector):
        # Get URL from the element or its closest anchor
        anchor = el if el.name == "a" else el.find("a")
        url = anchor["href"] if anchor and anchor.get("href") else ""

        # Get title: from title_selector scoped to this element, or anchor text
        if title_selector:
            title_el = el.select_one(title_selector)
            title = title_el.get_text(strip=True) if title_el else (anchor.get_text(strip=True) if anchor else "")
        else:
            title = (anchor.get_text(strip=True) if anchor else el.get_text(strip=True))

        title = title.strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        jobs.append({"title": title, "url": url, "description": "", "location": ""})

    return jobs


async def _fetch_js(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()

                # Block images/fonts/media to speed up load
                await page.route("**/*", lambda route: route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_())

                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # Scroll down in steps to trigger lazy-loaded job listings
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await asyncio.sleep(0.8)

                # Extra wait for XHR/fetch calls to settle
                await asyncio.sleep(3)

                html = await page.content()
                logger.debug("Fetched %d chars from %s", len(html), url)
                return html
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


def _extract_body_text(html: str) -> str:
    """Strip boilerplate tags and return line-structured text preserving block boundaries."""
    import re
    try:
        from bs4 import BeautifulSoup, NavigableString, Tag
    except ImportError:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    # Insert explicit newlines at block-level boundaries before extracting text
    BLOCK_TAGS = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                  "tr", "br", "dt", "dd", "blockquote"}
    for tag in soup.find_all(True):
        if tag.name in BLOCK_TAGS:
            tag.insert_before("\n")
            tag.insert_after("\n")

    raw = soup.get_text(separator="")
    # Normalise: collapse spaces within lines, collapse 3+ blank lines to 2
    lines = [" ".join(ln.split()) for ln in raw.splitlines()]
    # Remove duplicate consecutive lines (title repeated in meta/og tags etc.)
    deduped = []
    for ln in lines:
        if not deduped or ln != deduped[-1]:
            deduped.append(ln)
    text = "\n".join(deduped)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:4000]


def _normalise_job_url(url: str) -> str:
    """Return the job description URL, stripping apply/confirm suffixes."""
    import re
    # Workday and similar: strip /apply, /apply/autofillWithResume, /confirm etc.
    url = re.sub(r'/(apply|confirm|autofill[^?#]*)([\?#].*)?$', '', url, flags=re.IGNORECASE)
    return url.rstrip('/')


def _is_js_required(url: str) -> bool:
    """Return False for sites known to render server-side (Workday, Greenhouse, etc.)."""
    _NO_JS_DOMAINS = ('greenhouse.io', 'lever.co', 'ashbyhq.com', 'smartrecruiters.com')
    return not any(d in url for d in _NO_JS_DOMAINS)


async def _fetch_job_description(url: str) -> str:
    """Fetch one job detail page; return up to 3000 chars of cleaned body text."""
    url = _normalise_job_url(url)
    async with _desc_semaphore:
        html = None
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HTTP_HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    html = resp.text
        except Exception as e:
            logger.debug("HTTP desc fetch failed %s: %s", url, e)

        if html:
            text = _extract_body_text(html)
            if len(text) >= 200:
                return text[:3000]

        # Only try Playwright for JS-rendered sites
        if not _is_js_required(url):
            return ""

        try:
            html = await _fetch_js(url)
            if html:
                text = _extract_body_text(html)
                return text[:3000]
        except Exception as e:
            logger.debug("Playwright desc fetch failed %s: %s", url, e)

    return ""


async def _fetch_all_descriptions(company_id: int, force: bool = False):
    """Background task: fetch descriptions for jobs of a company.
    force=True re-fetches even jobs that already have a description.
    Saves incrementally in batches of 5 so the progress counter updates live.
    Respects _desc_fetch_cancel flag to abort early."""
    global _desc_fetch_active, _desc_fetch_done, _desc_fetch_current
    _desc_fetch_active += 1
    try:
        from .db import get_conn
        with get_conn() as conn:
            if force:
                jobs = conn.execute(
                    "SELECT id, url FROM jobs WHERE company_id=? AND is_expired=0 AND url != ''",
                    (company_id,)
                ).fetchall()
            else:
                jobs = conn.execute(
                    "SELECT id, url FROM jobs WHERE company_id=? AND is_expired=0 "
                    "AND (description IS NULL OR description='')",
                    (company_id,)
                ).fetchall()

        jobs_with_url = [j for j in jobs if j["url"]]
        if not jobs_with_url:
            return

        logger.info("Fetching descriptions for %d jobs (company %d)", len(jobs_with_url), company_id)
        total_saved = 0

        BATCH = 5
        for i in range(0, len(jobs_with_url), BATCH):
            if _desc_fetch_cancel:
                logger.info("Description fetch cancelled at job %d (company %d)", i, company_id)
                break

            batch = jobs_with_url[i:i + BATCH]
            # Update current URL indicator (first URL of batch)
            _desc_fetch_current = batch[0]["url"] if batch else ""

            results = await asyncio.gather(
                *[_fetch_job_description(j["url"]) for j in batch],
                return_exceptions=True
            )
            from .geo import extract_location_from_description, resolve_country
            with get_conn() as conn:
                for job, desc in zip(batch, results):
                    if isinstance(desc, Exception):
                        logger.warning("Description fetch error for job %s (%s): %s", job["id"], job["url"], desc)
                        _desc_fetch_done = min(_desc_fetch_done + 1, _desc_fetch_total)
                        continue
                    if isinstance(desc, str) and desc:
                        stored = conn.execute("SELECT title, location, posted_date FROM jobs WHERE id=?", (job["id"],)).fetchone()
                        existing_loc = stored["location"] or ""
                        is_vague = bool(re.match(r"^\d+\s+locations?$", existing_loc, re.IGNORECASE))

                        # Extract posted date from description (only set if not already known)
                        posted_date = stored["posted_date"] if stored["posted_date"] else extract_posted_date(desc)

                        # Always attempt location extraction from description
                        extracted_loc = extract_location_from_description(stored["title"] or "", desc)

                        final_loc = existing_loc
                        final_country = None  # None = don't update country

                        if extracted_loc:
                            if not existing_loc or is_vague:
                                # No prior location — use extracted
                                final_loc = extracted_loc
                                final_country = resolve_country(extracted_loc)
                            else:
                                # Both exist — compare normalised (lowercase, strip)
                                norm_existing = existing_loc.strip().lower()
                                norm_extracted = extracted_loc.strip().lower()
                                # Consider a match if either contains the other
                                # (e.g. "Munich" vs "Munich, Bavaria")
                                if norm_existing != norm_extracted and \
                                   norm_extracted not in norm_existing and \
                                   norm_existing not in norm_extracted:
                                    logger.warning(
                                        "Location mismatch job %s '%s': listing says %r, "
                                        "description says %r — overriding with description",
                                        job["id"], stored["title"] or "", existing_loc, extracted_loc
                                    )
                                    final_loc = extracted_loc
                                    final_country = resolve_country(extracted_loc)

                        if final_country is not None:
                            conn.execute(
                                "UPDATE jobs SET description=?, location=?, country=?, posted_date=? WHERE id=?",
                                (desc, final_loc, final_country, posted_date, job["id"])
                            )
                        elif final_loc != existing_loc:
                            conn.execute(
                                "UPDATE jobs SET description=?, location=?, posted_date=? WHERE id=?",
                                (desc, final_loc, posted_date, job["id"])
                            )
                        else:
                            conn.execute(
                                "UPDATE jobs SET description=?, posted_date=? WHERE id=?",
                                (desc, posted_date, job["id"])
                            )
                        total_saved += 1
                    # Cap at total to avoid counter exceeding 100%
                    _desc_fetch_done = min(_desc_fetch_done + 1, _desc_fetch_total)

        logger.info("Saved descriptions for %d/%d jobs (company %d)", total_saved, len(jobs_with_url), company_id)

        # Re-tag jobs for this company now that descriptions are populated
        try:
            from .tagger import tag_untagged_jobs
            tag_untagged_jobs()
        except Exception as e:
            logger.warning("Tagging after desc fetch failed for company %d: %s", company_id, e)

        if not _desc_fetch_cancel:
            # Resolve country for jobs that don't have one yet
            try:
                from .geo import resolve_countries_for_jobs
                with get_conn() as conn:
                    unresolved = conn.execute(
                        "SELECT id, location FROM jobs WHERE company_id=? AND is_expired=0 AND (country IS NULL OR country='')",
                        (company_id,)
                    ).fetchall()
                if unresolved:
                    resolved = resolve_countries_for_jobs([(r["id"], r["location"] or "") for r in unresolved])
                    with get_conn() as conn:
                        for jid, country in resolved:
                            if country:
                                conn.execute("UPDATE jobs SET country=? WHERE id=?", (country, jid))
            except Exception as e:
                logger.warning("Country resolution failed for company %d: %s", company_id, e)
    finally:
        _desc_fetch_active -= 1
        if _desc_fetch_active == 0:
            _desc_fetch_current = ""


async def run_scrape():
    """Main scrape loop — processes all companies sequentially with rate-limit handling."""
    global _scrape_started_at
    if _scrape_lock.locked():
        logger.warning("Scrape already in progress — skipping")
        return
    _scrape_started_at = time.monotonic()
    async with _scrape_lock:
        await _do_scrape()


async def _do_scrape():
    from .models import get_all_companies, upsert_job, mark_expired_jobs, log_scrape, get_setting
    from .llm import LLMRateLimitError

    logger.info("Daily scrape started at %s", datetime.now().isoformat())

    companies = get_all_companies()
    queue = list(companies)
    retry_counts: dict[int, int] = {}

    while queue:
        company = queue.pop(0)
        cid = company["id"]
        attempt = retry_counts.get(cid, 0)

        logger.info("Scraping %s (attempt %d)", company["name"], attempt + 1)

        try:
            jobs = await scrape_company(company)

            if jobs is None:
                retry_counts[cid] = attempt + 1
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    logger.warning("Scrape failed for %s — retrying in %ds", company["name"], wait)
                    log_scrape(cid, 0, "pending")
                    await asyncio.sleep(wait)
                    queue.append(company)
                else:
                    logger.error("Scrape permanently failed for %s", company["name"])
                    log_scrape(cid, 0, "failed")
                    _maybe_send_failure_alert(company, attempt + 1)
                continue

            # Upsert jobs
            seen_titles = []
            for job in jobs:
                title = job.get("title", "").strip()
                if not title:
                    continue
                seen_titles.append(title)
                upsert_job(
                    company_id=cid,
                    title=title,
                    description=job.get("description", ""),
                    url=job.get("url", ""),
                    location=job.get("location", ""),
                )

            # Mark jobs not seen this scrape as expired
            if seen_titles:
                mark_expired_jobs(cid, seen_titles)

            log_scrape(cid, len(seen_titles), "success")

            # Tag any new untagged jobs immediately (title-only, description may come later)
            try:
                from .tagger import tag_untagged_jobs
                tag_untagged_jobs()
            except Exception as e:
                logger.warning("Tagging after scrape failed for company %s: %s", company["name"], e)

            # Kick off description fetching in background (non-blocking)
            _safe_task(_fetch_all_descriptions(cid), name=f"desc-fetch-{cid}")
            logger.info("Scraped %d jobs from %s", len(seen_titles), company["name"])

        except LLMRateLimitError as e:
            wait = e.retry_after or 60
            logger.warning("Groq rate limit hit for %s — waiting %ds", company["name"], wait)
            log_scrape(cid, 0, "rate_limited")
            await asyncio.sleep(wait)
            queue.insert(0, company)  # retry immediately after wait

        except Exception as e:
            logger.exception("Unexpected error scraping %s: %s", company["name"], e)
            log_scrape(cid, 0, "failed")

    logger.info("Daily scrape complete — description fetching and matching running in background")


def _maybe_send_failure_alert(company: dict, consecutive_failures: int):
    if consecutive_failures >= 3:
        try:
            from .email_report import send_failure_alert
            send_failure_alert(company, consecutive_failures)
        except Exception as e:
            logger.warning("Failed to send scrape failure alert for %s: %s", company["name"], e)
