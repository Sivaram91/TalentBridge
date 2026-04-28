"""Playwright scraper with rate-limit-aware queue."""
import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Per-company retry config
MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 300]  # seconds between retries


async def scrape_company(company: dict) -> Optional[list[dict]]:
    """
    Scrape a single company's career page.
    Returns list of job dicts [{title, description, url, location}] or None on failure.
    Uses Gemini to extract structured data from raw HTML.
    """
    from .gemini import extract_jobs_from_html

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed")
        return None

    html = await _fetch_page(company["url"])
    if html is None:
        return None

    jobs = await extract_jobs_from_html(html, company["name"])
    return jobs


async def _fetch_page(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Allow JS to render
            await asyncio.sleep(2)
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


async def run_scrape():
    """Main scrape loop — processes all companies with rate-limit handling."""
    from .models import get_all_companies, upsert_job, mark_expired_jobs, log_scrape, get_setting
    from .gemini import GeminiRateLimitError

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
            logger.info("Scraped %d jobs from %s", len(seen_titles), company["name"])

        except GeminiRateLimitError as e:
            wait = e.retry_after or 60
            logger.warning("Gemini rate limit hit for %s — waiting %ds", company["name"], wait)
            log_scrape(cid, 0, "rate_limited")
            await asyncio.sleep(wait)
            queue.insert(0, company)  # retry immediately after wait

        except Exception as e:
            logger.exception("Unexpected error scraping %s: %s", company["name"], e)
            log_scrape(cid, 0, "failed")

    logger.info("Daily scrape complete")

    # Trigger matching after scrape
    try:
        from .matcher import run_matching
        await run_matching()
    except Exception as e:
        logger.exception("Matching failed: %s", e)


def _maybe_send_failure_alert(company: dict, consecutive_failures: int):
    if consecutive_failures >= 3:
        try:
            from .email_report import send_failure_alert
            send_failure_alert(company, consecutive_failures)
        except Exception:
            pass
