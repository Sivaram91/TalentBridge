"""AI calls — provider-configurable (groq/gemini/ollama) with Ollama fallback."""
import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Provider defaults
_PROVIDER_DEFAULTS = {
    "groq":   {"base": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.0-flash"},
    "ollama": {"base": "http://localhost:11434", "model": "llama3.2"},
}

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


class GeminiRateLimitError(Exception):
    """Kept as the canonical rate-limit error regardless of provider."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"AI rate limit — retry in {retry_after}s")


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


def _get_provider_config() -> tuple[str, str, str]:
    """Returns (provider, model, api_key)."""
    env = _read_env()
    provider = env.get("AI_PROVIDER", os.environ.get("AI_PROVIDER", "groq")).lower()
    if provider not in _PROVIDER_DEFAULTS:
        logger.warning("Unknown AI_PROVIDER '%s', falling back to groq", provider)
        provider = "groq"
    defaults = _PROVIDER_DEFAULTS[provider]
    model = env.get("AI_MODEL") or os.environ.get("AI_MODEL") or defaults["model"]
    key_map = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "ollama": ""}
    key_name = key_map.get(provider, "")
    api_key = (env.get(key_name) or os.environ.get(key_name, "")) if key_name else ""
    return provider, model, api_key


async def _call_openai_compat(base: str, api_key: str, model: str, prompt: str, temperature: float) -> str:
    """Call any OpenAI-compatible chat completions endpoint (Groq, etc.)."""
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 60))
        raise GeminiRateLimitError(retry_after)
    if resp.status_code != 200:
        raise RuntimeError(f"{base} error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


async def _call_gemini(base: str, api_key: str, model: str, prompt: str, temperature: float) -> str:
    url = f"{base}/models/{model}:generateContent?key={api_key}"
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
        raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response shape: {e}")


async def _call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    url = f"{OLLAMA_BASE}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama error {resp.status_code}")
    return resp.json().get("response", "")


async def _call_ai(prompt: str, temperature: float = 0.1) -> str:
    """Call configured provider, fall back to Ollama on non-rate-limit failure."""
    provider, model, api_key = _get_provider_config()
    try:
        if provider == "ollama":
            return await _call_ollama(prompt, model)
        elif provider == "gemini":
            defaults = _PROVIDER_DEFAULTS["gemini"]
            return await _call_gemini(defaults["base"], api_key, model, prompt, temperature)
        else:  # groq or any openai-compat
            defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["groq"])
            return await _call_openai_compat(defaults["base"], api_key, model, prompt, temperature)
    except GeminiRateLimitError:
        raise
    except Exception as e:
        if provider != "ollama":
            logger.warning("%s failed (%s), trying Ollama fallback", provider, e)
            return await _call_ollama(prompt)
        raise


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
    except GeminiRateLimitError:
        raise
    except Exception as e:
        logger.error("Keyword extraction failed: %s", e)
        return []


# ── Job extraction from HTML ─────────────────────────────────────────────────

def _preprocess_html(html: str) -> str:
    """Strip noise from HTML, keep text content and JSON blobs. Returns condensed string."""
    import re
    # Keep application/json and ld+json script blocks — they often contain structured job data
    cleaned = re.sub(
        r'<script(?![^>]*type=["\']application/(ld\+)?json)[^>]*>.*?</script>',
        '', html, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Strip all HTML tags, keeping text
    cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
    # Collapse whitespace
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


async def extract_jobs_from_html(html: str, company_name: str) -> list[dict]:
    """AI fallback for job extraction — only called when no CSS selector is configured
    or the selector returns nothing.
    Condenses HTML to plain text to stay within token limits.
    """
    # AI fallback — condense HTML to plain text first to stay within token limits
    import re
    condensed = _preprocess_html(html)
    # ~10k chars ≈ 2,500 tokens — well within Groq free tier limits
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
    except GeminiRateLimitError:
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
    except GeminiRateLimitError:
        raise
    except Exception as e:
        logger.error("Job scoring failed for '%s': %s", job_title, e)
        return {"score": 0, "reasoning": "Scoring unavailable."}
