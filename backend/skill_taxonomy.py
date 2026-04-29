"""
Build and cache a curated skill taxonomy from job descriptions.

Flow:
1. mine_candidates()  — frequency-rank terms across all descriptions
2. validate_with_llm() — LLM strictly filters to genuine job skills
3. Result stored in settings as skill_taxonomy_json
"""
from __future__ import annotations
import json
import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# ── Stopwords ────────────────────────────────────────────────────────────────
# Anything here is discarded before the LLM even sees it.
_STOPWORDS = {
    # English function / auxiliary
    "the","and","for","with","you","your","our","are","will","have","that","this",
    "from","they","their","been","were","has","can","may","not","but","use","its",
    "all","any","more","also","both","each","into","than","such","well","very",
    "who","what","how","when","where","which","about","would","should","could",
    "must","shall","being","had","did","does","doing","done","was","these","those",
    "own","get","got","let","set","put","run","see","need","want","like","just",
    "then","here","there","through","between","after","before","during","while",
    # Vague job-ad adjectives / nouns — never a skill
    "experience","years","year","knowledge","strong","ability","skills","skill",
    "good","great","required","preferred","using","ensure","support","help",
    "make","take","part","etc","other","related","new","existing","including",
    "within","across","team","work","based","join","role","position","job","hire",
    "via","per","incl","relevant","minimum","least","plus","high","key","main",
    "core","deep","broad","solid","proven","various","different","multiple",
    "several","following","responsible","responsibilities","opportunity","company",
    "environment","solutions","solution","systems","system","business","product",
    "products","service","services","process","processes","project","projects",
    "application","applications","development","implementation","management",
    "organization","organisation","team","teams","colleague","colleagues",
    "candidate","candidates","employee","employees","office","location","remote",
    "hybrid","full","time","part","permanent","contract","salary","benefit",
    "benefits","package","culture","growth","career","exciting","fast","paced",
    "growing","leading","world","global","international","local","national",
    "innovative","dynamic","passionate","motivated","proactive","excellent",
    "exceptional","outstanding","hands","driven","focused","oriented","based",
    "forward","looking","thinking","seeking","looking","offering","providing",
    "working","building","ensuring","managing","leading","supporting","developing",
    "delivering","creating","designing","implementing","maintaining","improving",
    "analyze","analyse","analyse","coordinate","communicate","collaborate",
    # German function words
    "eine","einen","einem","einer","eines","oder","und","die","der","das","den",
    "dem","des","ist","sind","wird","werden","kann","auch","bei","mit","von",
    "für","wie","ein","auf","aus","an","im","in","zu","um","als","nach","sich",
    "sowie","über","unter","wir","sie","ihr","uns","ihre","ihren","ihrem",
    "haben","sein","nicht","noch","aber","wenn","dann","damit","dabei","durch",
    "ohne","zwischen","gegen","während","bereits","gerne","werden","werden",
    "stellen","stelle","suchen","bieten","bringen","haben","sind","werden",
    "einem","einer","unsere","unser","unserer","ihrem","ihrer",
}

# Terms matching these patterns are almost never skills
_NOISE_RE = re.compile(
    r'^('
    r'\d.*'                          # starts with digit
    r'|.{1,2}$'                      # 1-2 chars
    r'|.*\b(tion|sion|ment|ness|ity|ance|ence|ship|ling|ings|ward|wards)$'  # generic nouns/suffixes
    r'|.*ly$'                        # adverbs
    r'|.*ful$|.*less$|.*ish$'        # adjectives
    r')',
    re.IGNORECASE,
)

_WORD_RE = re.compile(r'\b[a-zA-Z][a-zA-Z0-9\+\#\-\.]{2,}\b')


def mine_candidates(limit: int = 300) -> list[str]:
    """
    Scan all non-expired job descriptions. Return up to `limit` candidate
    terms ranked by document frequency (# distinct jobs containing the term).
    Only single words ≥4 chars and 2-word phrases are considered.
    """
    from .db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT description FROM jobs "
            "WHERE is_expired=0 AND description IS NOT NULL AND description != ''"
        ).fetchall()

    doc_freq: Counter = Counter()

    for row in rows:
        desc = row["description"].lower()
        words = _WORD_RE.findall(desc)
        seen: set[str] = set()

        for w in words:
            if (w not in _STOPWORDS
                    and len(w) >= 4
                    and not _NOISE_RE.match(w)):
                seen.add(w)

        # 2-word phrases
        tokens = desc.split()
        for i in range(len(tokens) - 1):
            a = tokens[i].strip('.,;:()[]"\'-–')
            b = tokens[i + 1].strip('.,;:()[]"\'-–')
            if (len(a) >= 3 and len(b) >= 3
                    and a not in _STOPWORDS and b not in _STOPWORDS
                    and not _NOISE_RE.match(a) and not _NOISE_RE.match(b)
                    and _WORD_RE.match(a) and _WORD_RE.match(b)):
                seen.add(f"{a} {b}")

        for term in seen:
            doc_freq[term] += 1

    # Must appear in ≥5 distinct jobs to be a real candidate
    candidates = [
        term for term, freq in doc_freq.most_common(limit * 4)
        if freq >= 5
    ]
    return candidates[:limit]


async def validate_with_llm(candidates: list[str], batch_size: int = 60) -> list[str]:
    """
    Strictly filter candidates to genuine job skills via LLM.
    On any failure, the batch is DROPPED (not kept) — we prefer precision.
    """
    from .gemini import _call_ai

    validated: list[str] = []

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        terms_str = json.dumps(batch, ensure_ascii=False)

        prompt = f"""You are a strict technical recruiter reviewing terms extracted from job postings.

Your task: from the list below, keep ONLY terms that are concrete, specific job skills — things a candidate would list on a CV under "Skills" or "Technical Skills".

KEEP: programming languages (Python, C++, Java), frameworks (React, Spring Boot), tools (Git, Jenkins, JIRA), protocols/standards (CAN bus, REST, AUTOSAR), domain-specific technologies (FPGA, PLC, ROS), certifications (PMP, CISSP), specific methodologies only if very specific (Scrum, Kanban).

DISCARD everything else, including:
- Generic nouns: "solution", "environment", "quality", "performance", "delivery"
- Vague adjectives/adverbs: "efficient", "robust", "scalable", "innovative"
- Job-ad filler: "passionate", "motivated", "fast-paced", "cross-functional"
- Soft skills: "communication", "leadership", "teamwork", "ownership"
- HR/company words: "culture", "diversity", "growth", "opportunity"
- Locations, company names, department names
- Anything you are unsure about — when in doubt, DISCARD

Input:
{terms_str}

Return ONLY a JSON array of kept terms, exact strings from input. If nothing qualifies, return [].
No explanation, no markdown, just the JSON array."""

        try:
            raw = await _call_ai(prompt, temperature=0.0)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            if isinstance(result, list):
                kept = [s for s in result if isinstance(s, str) and s in batch]
                validated.extend(kept)
                logger.info("Taxonomy batch %d: %d/%d kept", i, len(kept), len(batch))
        except Exception as e:
            logger.error("Taxonomy LLM validation failed (batch %d): %s — batch dropped", i, e)
            # Drop on failure — precision over recall

    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in validated:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


async def build_taxonomy() -> list[str]:
    """Mine → validate → store. Returns the final curated skill list."""
    from .models import set_setting

    logger.info("Taxonomy: mining candidates…")
    candidates = mine_candidates(limit=300)
    logger.info("Taxonomy: %d candidates mined, validating with LLM…", len(candidates))

    skills = await validate_with_llm(candidates)
    logger.info("Taxonomy: %d skills kept after LLM validation", len(skills))

    set_setting("skill_taxonomy_json", json.dumps(skills, ensure_ascii=False))
    set_setting("skill_taxonomy_count", str(len(skills)))
    return skills


def get_taxonomy() -> list[str]:
    """Return cached skill taxonomy, or [] if not built yet."""
    from .models import get_setting
    raw = get_setting("skill_taxonomy_json", "[]")
    try:
        return json.loads(raw)
    except Exception:
        return []
