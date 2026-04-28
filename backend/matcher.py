"""AI matching — scores all unmatched jobs against the current CV."""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def run_matching():
    """Score all unmatched (or stale) active jobs against the latest CV."""
    from .models import get_latest_cv, get_conn
    from .gemini import score_job_against_cv, GeminiRateLimitError
    from .db import get_conn

    cv = get_latest_cv()
    if not cv:
        logger.info("No CV uploaded — skipping matching")
        return

    keywords = json.loads(cv["keywords_json"])
    cv_text = cv["raw_text"]

    # Get active jobs that have no match record yet
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.id, j.title, j.description
            FROM jobs j
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE j.is_expired = 0 AND m.id IS NULL
        """).fetchall()

    jobs = [dict(r) for r in rows]
    logger.info("Matching %d unscored jobs", len(jobs))

    for job in jobs:
        try:
            result = await score_job_against_cv(
                job_title=job["title"],
                job_description=job.get("description") or "",
                cv_keywords=keywords,
                cv_text=cv_text,
            )
            from .models import save_match
            save_match(job["id"], result["score"], result["reasoning"])
        except GeminiRateLimitError as e:
            logger.warning("Rate limit during matching — waiting %ds", e.retry_after)
            await asyncio.sleep(e.retry_after)
            # retry this job
            try:
                result = await score_job_against_cv(
                    job_title=job["title"],
                    job_description=job.get("description") or "",
                    cv_keywords=keywords,
                    cv_text=cv_text,
                )
                from .models import save_match
                save_match(job["id"], result["score"], result["reasoning"])
            except Exception as e2:
                logger.error("Retry matching failed for job %d: %s", job["id"], e2)
        except Exception as e:
            logger.error("Matching failed for job %d: %s", job["id"], e)

    logger.info("Matching complete")
