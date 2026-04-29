"""Heuristic job matching — scores all unmatched jobs against the current CV."""
import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

_matching_active = False
_matching_started_at: float = 0.0


async def run_matching():
    """Score all unmatched active jobs against the latest CV."""
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
    from .models import get_latest_cv, save_match
    from .db import get_conn
    from .heuristic_match import heuristic_score
    from .skill_taxonomy import get_taxonomy

    cv = get_latest_cv()
    if not cv:
        logger.info("No CV — skipping matching")
        return
    all_kw = json.loads(cv["keywords_json"]) + json.loads(cv.get("extra_keywords_json") or "[]")
    all_kw = list(dict.fromkeys(all_kw))  # deduplicate, preserve order
    types: dict = json.loads(cv.get("keyword_types_json") or "{}")
    # Split into base and expert lists
    base_kw   = [k for k in all_kw if types.get(k) == "base"]
    expert_kw = [k for k in all_kw if types.get(k) != "base"]

    taxonomy = get_taxonomy()  # [] if not built yet

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.id, j.title, j.description
            FROM jobs j
            LEFT JOIN matches m ON m.job_id = j.id
            WHERE j.is_expired = 0 AND (m.id IS NULL OR m.is_override = 0)
        """).fetchall()
    jobs = [dict(r) for r in rows]
    logger.info("Scoring %d jobs — base: %d kw, expert: %d kw", len(jobs), len(base_kw), len(expert_kw))

    for job in jobs:
        score, detail = heuristic_score(
            job.get("description") or "", base_kw, expert_kw, taxonomy
        )
        reasoning = json.dumps(detail, ensure_ascii=False)
        save_match(job["id"], score, reasoning)

    logger.info("Matching complete — %d jobs scored", len(jobs))
