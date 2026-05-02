"""Deterministic per-company job description parser. No LLM involved."""
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParsedJob:
    valid: bool = False
    missing: list[str] = field(default_factory=list)
    role_bullets: list[str] = field(default_factory=list)
    qual_must: list[str] = field(default_factory=list)
    qual_nice: list[str] = field(default_factory=list)
    qual_other: list[str] = field(default_factory=list)
    language_required: str = "none"
    salary: str = ""
    location: str = ""
    posted: str = ""
    end_date: str = ""
    job_ref: str = ""


# ── Shared utilities ──────────────────────────────────────────────────────────

def _extract_bullets(block: str) -> list[str]:
    bullets = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "*", "·")):
            bullets.append(line.lstrip("-•*· ").strip())
        elif len(line) > 15:
            bullets.append(line)
    return bullets


_SALARY_RES = [
    re.compile(r'(?:€|EUR|USD|\$)?\s*(\d{2,3}[.,]?\d{0,3})\s*(?:k|tsd|\.000)?\s*[-–]\s*(?:€|EUR|USD|\$)?\s*(\d{2,3}[.,]?\d{0,3})\s*(?:k|tsd|\.000)?\s*(?:€|EUR|USD|\$|per year|p\.a\.)?', re.I),
    re.compile(r'(?:up to|bis zu)\s*(?:€|EUR|USD|\$)?\s*(\d{2,3}[.,]?\d{0,3})\s*(?:k|tsd|\.000)?\s*(?:€|EUR|USD|\$)?', re.I),
    re.compile(r'(?:salary|gehalt|vergütung)\s*:?\s*(?:€|EUR|USD|\$)?\s*(\d{2,3}[.,]?\d{0,3})', re.I),
]

def _extract_salary(text: str) -> str:
    for pat in _SALARY_RES:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return ""

_DE_MUST = re.compile(r'\b(deutsch|german)\b.{0,60}\b(erforderlich|vorausgesetzt|pflicht|required|mandatory|fließend|verhandlungssicher)\b', re.I | re.DOTALL)
_EN_MUST = re.compile(r'\b(english|englisch)\b.{0,60}\b(erforderlich|vorausgesetzt|pflicht|required|mandatory|fließend|verhandlungssicher)\b', re.I | re.DOTALL)
_DE_NICE = re.compile(r'\b(deutsch|german)\b.{0,60}\b(von vorteil|wünschenswert|nice.to.have|preferred|plus|advantage)\b', re.I | re.DOTALL)
_EN_NICE = re.compile(r'\b(english|englisch)\b.{0,60}\b(von vorteil|wünschenswert|nice.to.have|preferred|plus|advantage|would be a plus)\b', re.I | re.DOTALL)
_DE_STOPS = re.compile(r'\b(und|die|der|das|für|mit|ist|wir|sie|werden|bei|als|an|auf|im|von|zu|in)\b', re.I)

def _detect_language(all_bullets: list[str], full_text: str = "") -> str:
    text = " ".join(all_bullets) + " " + full_text
    de_must = bool(_DE_MUST.search(text))
    en_must = bool(_EN_MUST.search(text))
    if de_must and en_must:
        return "both_must"
    if de_must:
        return "german_must"
    if en_must:
        return "english_must"
    de_nice = bool(_DE_NICE.search(text))
    en_nice = bool(_EN_NICE.search(text))
    if de_nice:
        return "german_nice"
    if en_nice:
        return "english_nice"
    if len(_DE_STOPS.findall(text)) > 5:
        return "german_must"
    return "none"


def _section_between(text: str, start_anchor: str, end_anchors: list[str]) -> str:
    """Extract text between start_anchor and the first matching end_anchor."""
    idx = text.find(start_anchor)
    if idx == -1:
        return ""
    start = idx + len(start_anchor)
    end = len(text)
    for anchor in end_anchors:
        i = text.find(anchor, start)
        if i != -1 and i < end:
            end = i
    return text[start:end].strip()


# ── ABB parser ────────────────────────────────────────────────────────────────

_ABB_LOCATION_RE = re.compile(r'^locations?\s*\n(.+?)(?:\n|$)', re.I | re.M)
_ABB_POSTED_RE   = re.compile(r'posted\s+(\d+\s+\w+\s+ago|today|yesterday)', re.I)
_ABB_END_DATE_RE = re.compile(r'End Date:\s*([A-Za-z]+ \d+,\s*\d{4})', re.I)
_ABB_JOB_ID_RE   = re.compile(r'job requisition id\s*\n?\s*(\w+)', re.I)

_ABB_MUST_RE = re.compile(r'\bmust\s+have\b|\brequired\b|\bessential\b', re.I)
_ABB_NICE_RE = re.compile(r'\bis a plus\b|\bnice.to.have\b|\bpreferred\b|\badvantage\b|\bdesirable\b|\bwelcome\b', re.I)


def parse_abb(raw: str) -> ParsedJob:
    result = ParsedJob()
    missing = []

    m = _ABB_LOCATION_RE.search(raw)
    result.location = m.group(1).strip() if m else ""
    m = _ABB_POSTED_RE.search(raw)
    result.posted = m.group(1).strip() if m else ""
    m = _ABB_END_DATE_RE.search(raw)
    result.end_date = m.group(1).strip() if m else ""
    m = _ABB_JOB_ID_RE.search(raw)
    result.job_ref = m.group(1).strip() if m else ""
    result.salary = _extract_salary(raw)

    role_block = _section_between(raw, "You will be mainly accountable for", [
        "Qualifications for the role", "More about us"
    ])
    qual_block = _section_between(raw, "Qualifications for the role", ["More about us"])

    if not role_block:
        missing.append("role_section")
    if not qual_block:
        missing.append("qualifications_section")
    if "More about us" not in raw:
        missing.append("more_about_us_section")

    result.role_bullets = _extract_bullets(role_block)
    if role_block and not result.role_bullets:
        missing.append("role_bullets_empty")

    all_qual = _extract_bullets(qual_block)
    for b in all_qual:
        if _ABB_MUST_RE.search(b):
            result.qual_must.append(b)
        elif _ABB_NICE_RE.search(b):
            result.qual_nice.append(b)
        else:
            result.qual_other.append(b)

    result.language_required = _detect_language(all_qual, raw)
    result.missing = missing
    result.valid = len(missing) == 0
    return result


# ── Aconext parser ────────────────────────────────────────────────────────────

# Aconext uses German headers; both "Dein" (informal) and "Ihr" (formal) variants
_ACONEXT_ROLE_ANCHORS   = ["Dein Aufgabengebiet", "Ihr Aufgabengebiet"]
_ACONEXT_QUAL_ANCHORS   = ["Dein Profil", "Ihr Profil"]
_ACONEXT_END_ANCHORS    = ["Jetzt Online bewerben", "Deine Benefits", "Ihre Benefits", "Dein Ansprechpartner"]

_ACONEXT_LOC_RE     = re.compile(r'^([A-ZÜÄÖ][^\n]{2,40})\n\nVollzeit', re.M)
_ACONEXT_POSTED_RE  = re.compile(r'(\d+)\s*Tage?\s*(?:vor|ago)', re.I)

# Nice-to-have signals (end of bullet, German + English)
_ACONEXT_NICE_RE = re.compile(
    r'\b(ist von Vorteil|ist ein Vorteil|ist wünschenswert|von Vorteil|wünschenswert'
    r'|ist desirable|is desirable|is an advantage|is a plus|idealerweise|ideally)\b',
    re.I
)
# Must-have signals
_ACONEXT_MUST_RE = re.compile(
    r'\b(ist erforderlich|ist zwingend|ist vorausgesetzt|is required|zwingend erforderlich'
    r'|unbedingt erforderlich|Pflicht|wird vorausgesetzt)\b',
    re.I
)


def _aconext_find_section(text: str, anchors: list[str]) -> int:
    """Return char index of first matching anchor, or -1."""
    best = -1
    for anchor in anchors:
        idx = text.find(anchor)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    return best


def parse_aconext(raw: str) -> ParsedJob:
    result = ParsedJob()
    missing = []

    # Location: city appears just before "Vollzeit" on next line
    m = _ACONEXT_LOC_RE.search(raw)
    result.location = m.group(1).strip() if m else ""
    result.salary = _extract_salary(raw)

    role_idx = _aconext_find_section(raw, _ACONEXT_ROLE_ANCHORS)
    qual_idx = _aconext_find_section(raw, _ACONEXT_QUAL_ANCHORS)
    end_idx  = _aconext_find_section(raw, _ACONEXT_END_ANCHORS)

    if role_idx == -1:
        missing.append("role_section")
    if qual_idx == -1:
        missing.append("qualifications_section")

    # Role block: from role anchor to qual anchor (or end)
    if role_idx != -1:
        role_anchor_used = next(a for a in _ACONEXT_ROLE_ANCHORS if raw.find(a) == role_idx)
        role_start = role_idx + len(role_anchor_used)
        role_end = qual_idx if qual_idx != -1 and qual_idx > role_idx else (end_idx if end_idx != -1 else len(raw))
        role_block = raw[role_start:role_end].strip()
        result.role_bullets = _extract_bullets(role_block)

    # Qual block: from qual anchor to end anchor
    if qual_idx != -1:
        qual_anchor_used = next(a for a in _ACONEXT_QUAL_ANCHORS if raw.find(a) == qual_idx)
        qual_start = qual_idx + len(qual_anchor_used)
        qual_end = end_idx if end_idx != -1 and end_idx > qual_idx else len(raw)
        qual_block = raw[qual_start:qual_end].strip()
        all_qual = _extract_bullets(qual_block)
        for b in all_qual:
            if _ACONEXT_MUST_RE.search(b):
                result.qual_must.append(b)
            elif _ACONEXT_NICE_RE.search(b):
                result.qual_nice.append(b)
            else:
                result.qual_other.append(b)
        result.language_required = _detect_language(all_qual, raw)

    result.missing = missing
    result.valid = len(missing) == 0
    return result


# ── Airbus parser ─────────────────────────────────────────────────────────────

# Airbus uses German and English variants; collect all known header forms
_AIRBUS_ROLE_ANCHORS = [
    # German
    "Ihre Aufgaben und Verantwortlichkeiten",
    "Deine Aufgaben und Verantwortlichkeiten",
    "Deine Aufgaben:",
    "Ihre Aufgaben:",
    # English
    "Your tasks and responsibilities",
    "Your Tasks and Responsibilities",
    "Tasks and Responsibilities",
    "Duties & Responsibilities:",
    "Your Responsibilities:",
    "Tasks:",
]
_AIRBUS_QUAL_ANCHORS = [
    # German
    "Gewünschte Fähigkeiten und Qualifikationen",
    "Erforderliche Kenntnisse und Qualifikationen",
    "Gewünschte Kenntnisse und Qualifikationen",
    # English
    "Desired skills and qualifications",
    "Desired Skills and Qualifications",
    "Required skills and qualifications",
    "Required Skills and Qualifications",
    "Required Skills:",
    "Qualifications:",
]
_AIRBUS_END_ANCHORS = [
    "Keine 100%ige Übereinstimmung",
    "Not a 100% match",
    "We Offer:",
    "Deine Vorteile",
    "Ihre Vorteile",
    "Wir bieten",
    "What we offer",
    "#CI_",
    "This job requires an awareness",
    "Similar Jobs",
]

_AIRBUS_LOCATION_RE = re.compile(r'^locations?\s*\n(.+?)(?:\n|$)', re.I | re.M)
_AIRBUS_POSTED_RE   = re.compile(r'posted\s+(\d+\s+\w+\s+ago|today|yesterday)', re.I)
_AIRBUS_END_DATE_RE = re.compile(r'End Date:\s*([A-Za-z]+ \d+,\s*\d{4})', re.I)
_AIRBUS_JOB_ID_RE   = re.compile(r'job requisition id\s*\n?\s*(\w+)', re.I)

_AIRBUS_NICE_RE = re.compile(
    r'\b(idealerweise|ideally|would be a plus|is an advantage|is a plus'
    r'|von Vorteil|wünschenswert|desirable|preferred|advantageous'
    r'|wäre von Vorteil|wäre ein Plus)\b',
    re.I
)


def _airbus_find_section(text: str, anchors: list[str]) -> tuple[int, str]:
    """Return (char_index, matched_anchor) for first anchor found, or (-1, '')."""
    best_idx, best_anchor = -1, ""
    for anchor in anchors:
        idx = text.find(anchor)
        if idx != -1 and (best_idx == -1 or idx < best_idx):
            best_idx, best_anchor = idx, anchor
    return best_idx, best_anchor


def _bullets_only(block: str) -> list[str]:
    """Extract only bullet-point lines (- or •), skip plain paragraphs."""
    bullets = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "*", "·")):
            text = line.lstrip("-•*· ").strip()
            if text:
                bullets.append(text)
    return bullets


def parse_airbus(raw: str) -> ParsedJob:
    result = ParsedJob()
    missing = []

    m = _AIRBUS_LOCATION_RE.search(raw)
    result.location = m.group(1).strip() if m else ""
    m = _AIRBUS_POSTED_RE.search(raw)
    result.posted = m.group(1).strip() if m else ""
    m = _AIRBUS_END_DATE_RE.search(raw)
    result.end_date = m.group(1).strip() if m else ""
    m = _AIRBUS_JOB_ID_RE.search(raw)
    result.job_ref = m.group(1).strip() if m else ""
    result.salary = _extract_salary(raw)

    role_idx, role_anchor = _airbus_find_section(raw, _AIRBUS_ROLE_ANCHORS)
    qual_idx, qual_anchor = _airbus_find_section(raw, _AIRBUS_QUAL_ANCHORS)
    end_idx,  _           = _airbus_find_section(raw, _AIRBUS_END_ANCHORS)

    if role_idx == -1:
        missing.append("role_section")
    if qual_idx == -1:
        missing.append("qualifications_section")

    if role_idx != -1:
        role_start = role_idx + len(role_anchor)
        role_end = qual_idx if qual_idx != -1 and qual_idx > role_idx else (end_idx if end_idx != -1 else len(raw))
        result.role_bullets = _bullets_only(raw[role_start:role_end])

    if qual_idx != -1:
        qual_start = qual_idx + len(qual_anchor)
        qual_end = end_idx if end_idx != -1 and end_idx > qual_idx else len(raw)
        all_qual = _bullets_only(raw[qual_start:qual_end])
        for b in all_qual:
            if _AIRBUS_NICE_RE.search(b):
                result.qual_nice.append(b)
            else:
                result.qual_must.append(b)
        result.language_required = _detect_language(all_qual, raw)

    result.missing = missing
    result.valid = len(missing) == 0
    return result


# ── Dispatcher ────────────────────────────────────────────────────────────────

# Map company_id → parser function
_PARSERS = {
    1: parse_abb,
    2: parse_aconext,
    3: parse_airbus,
}


def parse_job_description(company_id: int, raw: str) -> ParsedJob | None:
    """Parse a raw description deterministically. Returns None if no parser for company."""
    parser = _PARSERS.get(company_id)
    if parser is None:
        return None
    try:
        return parser(raw)
    except Exception as e:
        logger.warning("Parser failed for company %d: %s", company_id, e)
        return None


def parsed_to_dict(parsed: ParsedJob, title: str, company_name: str) -> dict:
    """Convert ParsedJob to the structured_description JSON dict stored in DB."""
    return {
        "role":              title,
        "company":           company_name,
        "location":          parsed.location,
        "salary":            parsed.salary,
        "language_required": parsed.language_required,
        "role_description":  parsed.role_bullets,
        "qualifications":    parsed.qual_other,
        "skills_must":       parsed.qual_must,
        "skills_nice":       parsed.qual_nice,
        "parse_valid":       parsed.valid,
        "parse_missing":     parsed.missing,
    }
