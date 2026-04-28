"""AI matching — scores all unmatched jobs against the current CV."""
import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

_matching_active = False
_matching_started_at: float = 0.0


async def run_matching():
    """Score all unmatched (or stale) active jobs against the latest CV."""
    global _matching_active, _matching_started_at
    if _matching_active:
        logger.info("Matching already in progress — skipping")
        return
    _matching_active = True
    _matching_started_at = time.monotonic()
    try:
        await _do_matching()
    finally:
        _matching_active = False


async def _do_matching():
    from .models import get_latest_cv, get_conn
    from .gemini import score_job_against_cv, GeminiRateLimitError
    from .db import get_conn

    cv = get_latest_cv()
    if not cv:
        logger.info("No CV uploaded — skipping matching")
        return

    keywords = json.loads(cv["keywords_json"])
    cv_text = cv["raw_text"]

    # Only score jobs that have a description AND no match record yet
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.id, j.title, j.description
            FROM jobs j
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE j.is_expired = 0
              AND m.id IS NULL
              AND j.description IS NOT NULL
              AND j.description != ''
        """).fetchall()

    jobs = [dict(r) for r in rows]
    logger.info("Matching %d unscored jobs", len(jobs))

    from .models import save_match

    for i, job in enumerate(jobs):
        # Pace requests to stay within free-tier TPM limits
        if i > 0:
            await asyncio.sleep(2)

        retry = True
        while retry:
            retry = False
            try:
                result = await score_job_against_cv(
                    job_title=job["title"],
                    job_description=job.get("description") or "",
                    cv_keywords=keywords,
                    cv_text=cv_text,
                )
                save_match(job["id"], result["score"], result["reasoning"])
            except GeminiRateLimitError as e:
                wait = e.retry_after or 60
                logger.warning("Rate limit during matching — waiting %ds", wait)
                await asyncio.sleep(wait)
                retry = True
            except Exception as e:
                logger.error("Matching failed for job %d: %s", job["id"], e)

    logger.info("Matching complete")
