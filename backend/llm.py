"""LLM calls — Groq free tier (llama-3.3-70b-versatile) via OpenAI-compatible API."""
import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_GROQ_BASE  = "https://api.groq.com/openai/v1"
_GROQ_MODEL = "llama-3.3-70b-versatile"


class LLMRateLimitError(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"LLM rate limit — retry in {retry_after}s")


def _read_env() -> dict:
    env_path = Path(__file__).parent.parent / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _get_api_key() -> str:
    env = _read_env()
    return env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")


async def _call_ai(prompt: str, temperature: float = 0.1) -> str:
    api_key = _get_api_key()
    url = f"{_GROQ_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 60))
        raise LLMRateLimitError(retry_after)
    if resp.status_code != 200:
        raise RuntimeError(f"Groq error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


# ── CV keyword extraction ────────────────────────────────────────────────────

_CV_CHUNK_SIZE = 12000
_CV_PROMPT = """Extract every concrete professional skill, technology, tool, and domain knowledge item from this CV text.

KEEP: programming languages, frameworks, libraries, tools, protocols, standards, hardware platforms, certifications, domain-specific methodologies.
DISCARD: soft skills, generic adjectives, personal details, company names, job titles, locations, dates.

Use canonical short forms (e.g. "C++" not "proficiency in C++", "ISO 14229" not "ISO-14229 standard").
Return ONLY a JSON array of strings. No explanation, no markdown.

CV TEXT:
{chunk}"""


def _parse_keywords_json(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    if isinstance(result, list):
        return [k.strip() for k in result if isinstance(k, str) and k.strip()]
    return []


async def _call_ai_with_retry(prompt: str, temperature: float = 0.0) -> str:
    import asyncio
    for attempt in range(5):
        try:
            return await _call_ai(prompt, temperature=temperature)
        except LLMRateLimitError as e:
            wait = e.retry_after + 5
            logger.info("Rate limited, waiting %ds (attempt %d/5)…", wait, attempt + 1)
            await asyncio.sleep(wait)
    raise RuntimeError("Gave up after 5 rate-limit retries")


async def extract_cv_keywords(cv_text: str) -> list[str]:
    chunks = [cv_text[i:i + _CV_CHUNK_SIZE] for i in range(0, len(cv_text), _CV_CHUNK_SIZE)]
    logger.info("CV extraction: %d chunk(s) for %d chars", len(chunks), len(cv_text))

    seen: set[str] = set()
    keywords: list[str] = []

    for idx, chunk in enumerate(chunks):
        prompt = _CV_PROMPT.format(chunk=chunk)
        try:
            raw = await _call_ai_with_retry(prompt)
            extracted = _parse_keywords_json(raw)
            new = 0
            for k in extracted:
                if k.lower() not in seen:
                    seen.add(k.lower())
                    keywords.append(k)
                    new += 1
            logger.info("CV extraction: chunk %d/%d — %d new skills", idx + 1, len(chunks), new)
        except Exception as e:
            logger.error("CV extraction failed on chunk %d: %s", idx + 1, e)

    logger.info("CV extraction: total %d skills extracted", len(keywords))
    return keywords


# ── Job extraction from HTML ─────────────────────────────────────────────────

def _preprocess_html(html: str) -> str:
    import re
    cleaned = re.sub(
        r'<script(?![^>]*type=["\']application/(ld\+)?json)[^>]*>.*?</script>',
        '', html, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


async def extract_jobs_from_html(html: str, company_name: str) -> list[dict]:
    condensed = _preprocess_html(html)
    trimmed = condensed[:10000]

    prompt = f"""Extract job listings from this career page text.
Company: {company_name}

Return a JSON array. Each item must have:
- "title": string (job title)
- "url": string (link to job, or "")
- "location": string (city/country, or "")
- "description": string (brief description, or "")

Return ONLY the JSON array. If no jobs found, return [].

PAGE TEXT:
{trimmed}"""

    try:
        raw = await _call_ai(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        jobs = json.loads(raw)
        if not isinstance(jobs, list):
            return []
        valid = []
        for j in jobs:
            if isinstance(j, dict) and j.get("title"):
                valid.append({
                    "title": str(j.get("title", ""))[:200],
                    "description": str(j.get("description", ""))[:500],
                    "url": str(j.get("url", ""))[:500],
                    "location": str(j.get("location", ""))[:100],
                })
        return valid
    except LLMRateLimitError:
        raise
    except Exception as e:
        logger.error("Job extraction failed for %s: %s", company_name, e)
        return []


# ── Job matching ─────────────────────────────────────────────────────────────

async def score_job_against_cv(
    job_title: str,
    job_description: str,
    cv_keywords: list[str],
    cv_text: str,
) -> dict:
    keywords_str = ", ".join(cv_keywords[:30])
    prompt = f"""You are a job-matching assistant. Score how well this job matches the candidate's profile.

Job Title: {job_title}
Job Description: {job_description[:800]}

Candidate Keywords: {keywords_str}

Return ONLY a JSON object with:
- "score": integer 0-100 (0=no match, 100=perfect match)
- "reasoning": string (one sentence explaining the score, max 120 chars)

Example: {{"score": 72, "reasoning": "Strong Python and ML overlap; cloud experience aligns well."}}"""

    try:
        raw = await _call_ai(prompt, temperature=0.0)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        score = max(0, min(100, int(result.get("score", 0))))
        reasoning = str(result.get("reasoning", ""))[:200]
        return {"score": score, "reasoning": reasoning}
    except LLMRateLimitError:
        raise
    except Exception as e:
        logger.error("Job scoring failed for '%s': %s", job_title, e)
        return {"score": 0, "reasoning": "Scoring unavailable."}
