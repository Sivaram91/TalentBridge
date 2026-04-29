"""Keyword-overlap job matching with base / expert skill tiers."""
import re

_WORD_RE = re.compile(r'\b[a-zA-Z][a-zA-Z0-9\+\#\-\.]{1,}\b')


def _hits(text: str, keywords: list[str]) -> list[str]:
    """Return keywords found in text (word-boundary, case-insensitive)."""
    t = text.lower()
    return [kw for kw in keywords
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', t)]


def _missing_from_taxonomy(desc: str, cv_keywords: list[str],
                            taxonomy: list[str], limit: int = 8) -> list[str]:
    """Taxonomy skills present in job description but not covered by CV."""
    desc_l = desc.lower()
    cv_lower = {kw.lower() for kw in cv_keywords}
    missing = []
    for skill in taxonomy:
        s = skill.lower()
        if any(s in kw or kw in s for kw in cv_lower):
            continue
        if re.search(r'\b' + re.escape(s) + r'\b', desc_l):
            missing.append(skill)
        if len(missing) >= limit:
            break
    return missing


def heuristic_score(
    description: str,
    base_keywords: list[str],
    expert_keywords: list[str],
    taxonomy: list[str] | None = None,
) -> tuple[int, dict]:
    """
    Score a job description against base + expert CV skills.

    Scoring:
      - Any base skill hit guarantees score ≥ 50 (job is within your field).
      - Each additional expert skill hit adds 5 points on top.
      - If no base skills defined, each expert hit = 10 points.
      - Capped at 100.

    Returns (score, detail_dict).
    """
    desc = description or ""
    all_keywords = base_keywords + expert_keywords

    if not all_keywords or len(desc) < 20:
        return 0, {
            "matched_base": [], "matched_expert": [],
            "missing": [], "has_base": len(base_keywords) > 0,
            "score_note": "No description available",
        }

    matched_base   = _hits(desc, base_keywords)
    matched_expert = _hits(desc, expert_keywords)

    if base_keywords:
        if matched_base:
            score = 50 + len(matched_expert) * 5
        else:
            # Base skills defined but none found — low score even with expert hits
            score = len(matched_expert) * 3
    else:
        # No base skills defined — use expert hits only (10 pts each)
        score = len(matched_expert) * 10

    score = min(100, score)

    missing = _missing_from_taxonomy(desc, all_keywords, taxonomy or [])

    base_count   = len(matched_base)
    expert_count = len(matched_expert)
    if base_keywords and matched_base:
        note = f"{base_count} base + {expert_count} expert skills matched"
    elif base_keywords and not matched_base:
        note = f"No base skills found — {expert_count} expert skill{'s' if expert_count != 1 else ''} matched"
    else:
        note = f"{expert_count} skill{'s' if expert_count != 1 else ''} matched"

    return score, {
        "matched_base":   matched_base,
        "matched_expert": matched_expert,
        "missing":        missing,
        "has_base":       len(base_keywords) > 0,
        "score_note":     note,
    }
