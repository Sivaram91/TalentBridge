"""
Build and cache a curated skill taxonomy from job descriptions.

Flow:
1. Seed — send first job description to Groq, extract skills as the seed taxonomy
2. Heuristic pass — for each remaining job, check what % of current taxonomy
   skills appear in the description text (case-insensitive substring match).
   If hit rate >= 20%: merge the matched skills (no LLM needed).
   If hit rate <  20%: description likely has skills not in the taxonomy yet
   — send to Groq, extract fresh skills, merge any new ones in.
3. Result stored in settings as skill_taxonomy_json.
"""
from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger(__name__)


# ── LLM extraction ────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """You are a technical recruiter reading a job description.

Extract ONLY the concrete skills, technologies, tools, and domain knowledge that a candidate must or should have. Focus on the requirements / qualifications / "Dein Profil" / "What you bring" section — ignore company marketing, benefits, and job responsibilities.

KEEP: programming languages, frameworks, libraries, tools, protocols, standards, hardware platforms, certifications, domain-specific methodologies (e.g. Scrum, ASPICE, Kanban).
DISCARD: soft skills, generic adjectives, vague nouns, location, salary, company description.

Return ONLY a JSON array of skill strings. Use the canonical short form (e.g. "C++" not "proficiency in C++"). If no concrete skills found, return [].
No explanation, no markdown — just the JSON array.

JOB DESCRIPTION:
{desc}"""


def _parse_llm_json(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    if isinstance(result, list):
        return [s.strip() for s in result if isinstance(s, str) and s.strip()]
    return []


async def _extract_skills_llm(description: str) -> list[str]:
    import asyncio
    from .llm import _call_ai, LLMRateLimitError
    prompt = _EXTRACT_PROMPT.format(desc=description[:8000])
    for attempt in range(5):
        try:
            raw = await _call_ai(prompt, temperature=0.0)
            skills = _parse_llm_json(raw)
            logger.info("Taxonomy LLM: extracted %d skills", len(skills))
            return skills
        except LLMRateLimitError as e:
            wait = e.retry_after + 5
            logger.info("Taxonomy LLM: rate limited, waiting %ds (attempt %d/5)…", wait, attempt + 1)
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error("Taxonomy LLM extraction failed: %s", e)
            return []
    logger.error("Taxonomy LLM: gave up after 5 rate-limit retries")
    return []


# ── Heuristic match ───────────────────────────────────────────────────────────

def _heuristic_hit_rate(taxonomy: list[str], description: str) -> tuple[float, list[str]]:
    """Return (hit_rate 0-1, list_of_matched_skills)."""
    if not taxonomy:
        return 0.0, []
    desc_lower = description.lower()
    matched = [s for s in taxonomy if s.lower() in desc_lower]
    return len(matched) / len(taxonomy), matched


# ── Deduplication ─────────────────────────────────────────────────────────────

def _merge(taxonomy: list[str], new_skills: list[str]) -> list[str]:
    """Append skills not already in taxonomy (case-insensitive dedup)."""
    existing = {s.lower() for s in taxonomy}
    for s in new_skills:
        if s.lower() not in existing:
            taxonomy.append(s)
            existing.add(s.lower())
    return taxonomy


# ── Main build ────────────────────────────────────────────────────────────────

async def build_taxonomy() -> list[str]:
    """Seed from first job → heuristic/LLM pass over remaining → store."""
    from .db import get_conn
    from .models import set_setting

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, description FROM jobs "
            "WHERE is_expired=0 AND description IS NOT NULL AND description != '' "
            "ORDER BY id"
        ).fetchall()

    jobs = [dict(r) for r in rows]
    if not jobs:
        logger.warning("Taxonomy: no job descriptions found")
        set_setting("skill_taxonomy_json", "[]")
        set_setting("skill_taxonomy_count", "0")
        return []

    logger.info("Taxonomy: %d job descriptions to process", len(jobs))

    # Step 1 — seed from first job
    taxonomy: list[str] = []
    seed_skills = await _extract_skills_llm(jobs[0]["description"])
    taxonomy = _merge(taxonomy, seed_skills)
    logger.info("Taxonomy: seeded with %d skills from '%s'", len(taxonomy), jobs[0]["title"])

    llm_calls = 1

    # Step 2 — heuristic + selective LLM for the rest
    for job in jobs[1:]:
        desc = job["description"]
        hit_rate, _ = _heuristic_hit_rate(taxonomy, desc)

        if hit_rate >= 0.20:
            logger.info(
                "Taxonomy: '%s' — heuristic %.0f%% hit, skipping LLM",
                job["title"], hit_rate * 100,
            )
        else:
            logger.info(
                "Taxonomy: '%s' — heuristic %.0f%% hit (<20%%), sending to LLM",
                job["title"], hit_rate * 100,
            )
            new_skills = await _extract_skills_llm(desc)
            before = len(taxonomy)
            taxonomy = _merge(taxonomy, new_skills)
            llm_calls += 1
            logger.info(
                "Taxonomy: added %d new skills (total %d)",
                len(taxonomy) - before, len(taxonomy),
            )

    logger.info(
        "Taxonomy: done — %d skills, %d LLM calls for %d jobs",
        len(taxonomy), llm_calls, len(jobs),
    )

    set_setting("skill_taxonomy_json", json.dumps(taxonomy, ensure_ascii=False))
    set_setting("skill_taxonomy_count", str(len(taxonomy)))
    return taxonomy


def get_taxonomy() -> list[str]:
    """Return cached skill taxonomy, or [] if not built yet."""
    from .models import get_setting
    raw = get_setting("skill_taxonomy_json", "[]")
    try:
        return json.loads(raw)
    except Exception:
        return []


# ── Clustering ────────────────────────────────────────────────────────────────

_CLUSTER_PROMPT = """You are a technical skills taxonomy expert.

Group the following job skills into named clusters. Each cluster should represent a coherent technical domain (e.g. "Communication Protocols", "Embedded OS & RTOS", "Testing & Validation Tools").

Rules:
- Every skill must appear in exactly one cluster
- Cluster names should be concise and domain-specific (3-5 words max)
- Each cluster should have 3-30 skills
- Assign 1-3 short domain tags per cluster from this fixed set: embedded, automotive, networking, software, tooling, safety, hardware, testing, methodology, cloud, data, security
- Aim for 5-15 clusters from this batch

Return ONLY a JSON array of cluster objects, no explanation, no markdown:
[
  {{
    "name": "Communication Protocols",
    "skills": ["CAN", "FlexRay", "LIN", "Ethernet", "I2C", "SPI", "UART"],
    "domain_tags": ["embedded", "networking", "automotive"]
  }},
  ...
]

SKILLS TO CLUSTER:
{skills}"""

_CLUSTER_BATCH_SIZE = 150


def _parse_cluster_response(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    if not isinstance(result, list):
        raise ValueError("Expected a list")
    valid = []
    for c in result:
        if not isinstance(c, dict) or not c.get("name") or not isinstance(c.get("skills"), list):
            continue
        skills = [s for s in c["skills"] if isinstance(s, str) and s.strip()]
        domain_tags = [t for t in (c.get("domain_tags") or []) if isinstance(t, str)]
        if skills:
            valid.append({"name": c["name"].strip(), "skills": skills, "domain_tags": domain_tags})
    return valid


async def _cluster_batch(batch: list[str]) -> list[dict]:
    import asyncio
    from .llm import _call_ai, LLMRateLimitError
    prompt = _CLUSTER_PROMPT.format(skills=json.dumps(batch, ensure_ascii=False))
    for attempt in range(5):
        try:
            raw = await _call_ai(prompt, temperature=0.0)
            return _parse_cluster_response(raw)
        except LLMRateLimitError as e:
            wait = e.retry_after + 5
            logger.info("Clustering: rate limited, waiting %ds (attempt %d/5)…", wait, attempt + 1)
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error("Clustering batch failed: %s", e)
            return []
    logger.error("Clustering: gave up after 5 retries")
    return []


async def build_clusters(taxonomy: list[str]) -> list[dict]:
    """Batch taxonomy into chunks → cluster each → merge same-named clusters → store."""
    from .db import get_conn

    if not taxonomy:
        return []

    batches = [taxonomy[i:i + _CLUSTER_BATCH_SIZE] for i in range(0, len(taxonomy), _CLUSTER_BATCH_SIZE)]
    logger.info("Clustering: %d skills in %d batches of ~%d", len(taxonomy), len(batches), _CLUSTER_BATCH_SIZE)

    # Collect clusters across all batches, merging by name (case-insensitive)
    merged: dict[str, dict] = {}  # name_lower → cluster dict
    clustered_lower: set[str] = set()

    for idx, batch in enumerate(batches):
        logger.info("Clustering: batch %d/%d (%d skills)…", idx + 1, len(batches), len(batch))
        clusters = await _cluster_batch(batch)
        for c in clusters:
            key = c["name"].lower()
            if key in merged:
                # Same cluster name appeared in a previous batch — merge skills into it
                existing = merged[key]
                existing_lower = {s.lower() for s in existing["skills"]}
                for s in c["skills"]:
                    if s.lower() not in existing_lower:
                        existing["skills"].append(s)
                        existing_lower.add(s.lower())
                # Union domain tags
                existing["domain_tags"] = list(set(existing["domain_tags"]) | set(c["domain_tags"]))
            else:
                merged[key] = c
            clustered_lower.update(s.lower() for s in c["skills"])

    valid_clusters = list(merged.values())

    # Orphaned skills (any batch that failed) → "Other"
    orphans = [s for s in taxonomy if s.lower() not in clustered_lower]
    if orphans:
        logger.info("Clustering: %d orphaned skills → 'Other' cluster", len(orphans))
        valid_clusters.append({"name": "Other", "skills": orphans, "domain_tags": []})

    logger.info("Clustering: %d clusters from %d skills", len(valid_clusters), len(taxonomy))

    with get_conn() as conn:
        conn.execute("DELETE FROM skill_clusters")
        for c in valid_clusters:
            conn.execute(
                """INSERT INTO skill_clusters (name, skills_json, domain_tags_json, skill_count)
                   VALUES (?, ?, ?, ?)""",
                (c["name"],
                 json.dumps(c["skills"], ensure_ascii=False),
                 json.dumps(c["domain_tags"], ensure_ascii=False),
                 len(c["skills"])),
            )

    return valid_clusters


def get_clusters() -> list[dict]:
    """Return stored clusters from DB."""
    from .db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, skills_json, domain_tags_json, skill_count FROM skill_clusters ORDER BY CASE WHEN name='Other' THEN 1 ELSE 0 END, skill_count DESC"
        ).fetchall()
    result = []
    for r in rows:
        try:
            result.append({
                "name": r["name"],
                "skills": json.loads(r["skills_json"]),
                "domain_tags": json.loads(r["domain_tags_json"]),
                "skill_count": r["skill_count"],
            })
        except Exception:
            continue
    return result
