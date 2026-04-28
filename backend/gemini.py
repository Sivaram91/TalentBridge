"""Gemini API calls with rate limit handling and Ollama fallback."""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-1.5-flash"

# Ollama fallback
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


class GeminiRateLimitError(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Gemini rate limit — retry in {retry_after}s")


def _get_api_key() -> str:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("GEMINI_API_KEY", "")


async def _call_gemini(prompt: str, temperature: float = 0.1) -> str:
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("No Gemini API key configured")

    url = f"{GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 60))
        raise GeminiRateLimitError(retry_after)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response shape: {e}")


async def _call_ollama(prompt: str) -> str:
    """Fallback to local Ollama when Gemini is unavailable."""
    url = f"{OLLAMA_BASE}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama error {resp.status_code}")
    return resp.json().get("response", "")


async def _call_ai(prompt: str, temperature: float = 0.1) -> str:
    """Call Gemini, fall back to Ollama on failure (except rate limits)."""
    try:
        return await _call_gemini(prompt, temperature)
    except GeminiRateLimitError:
        raise  # let caller handle rate limits
    except Exception as e:
        logger.warning("Gemini failed (%s), trying Ollama fallback", e)
        return await _call_ollama(prompt)


# ── CV keyword extraction ────────────────────────────────────────────────────

async def extract_cv_keywords(cv_text: str) -> list[str]:
    prompt = f"""Extract the key professional skills, technologies, tools, and domain knowledge
from this CV. Return ONLY a JSON array of strings — no explanation, no markdown, just the array.
Limit to the 30 most important and specific keywords.

CV:
{cv_text[:6000]}

Return format: ["Python", "Machine Learning", ...]"""

    try:
        raw = await _call_ai(prompt)
        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        keywords = json.loads(raw)
        return [k for k in keywords if isinstance(k, str)]
    except Exception as e:
        logger.error("Keyword extraction failed: %s", e)
        return []


# ── Job extraction from HTML ─────────────────────────────────────────────────

async def extract_jobs_from_html(html: str, company_name: str) -> list[dict]:
    """Extract structured job listings from raw career page HTML."""
    # Trim HTML — send first 12k chars to stay within token budget
    trimmed = html[:12000]

    prompt = f"""You are extracting job listings from a company's career page HTML.
Company: {company_name}

Return a JSON array of job objects. Each object must have these fields:
- "title": string (job title)
- "description": string (brief description, max 300 chars, or empty string)
- "url": string (direct link to job posting, or empty string)
- "location": string (city/country/remote, or empty string)

Return ONLY the JSON array. No explanation, no markdown fences.
If no jobs are found, return an empty array [].

HTML:
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
        # Validate shape
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
    """
    Returns {"score": int 0-100, "reasoning": str}
    """
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
    except Exception as e:
        logger.error("Job scoring failed for '%s': %s", job_title, e)
        return {"score": 0, "reasoning": "Scoring unavailable."}
