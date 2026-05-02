"""
ABB job description parser + validator.
Run: python scripts/abb_parser.py

Validates that each ABB job description matches the known ABB format, then
extracts and pretty-prints structured data. No LLM used.
"""

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "talentbridge.db"

# ── Patterns ──────────────────────────────────────────────────────────────────

_LOCATION_RE   = re.compile(r'^locations?\s*\n(.+?)(?:\n|$)', re.I | re.M)
_POSTED_RE     = re.compile(r'posted\s+(\d+\s+\w+\s+ago|today|yesterday)', re.I)
_END_DATE_RE   = re.compile(r'End Date:\s*([A-Za-z]+ \d+,\s*\d{4})', re.I)
_JOB_ID_RE     = re.compile(r'job requisition id\s*\n?\s*(\w+)', re.I)

# Section anchors
_ROLE_ANCHOR   = "You will be mainly accountable for"
_QUAL_ANCHOR   = "Qualifications for the role"
_END_ANCHOR    = "More about us"

# Qualification sub-classifiers
_MUST_RE = re.compile(r'\bmust\s+have\b|\brequired\b|\bessential\b', re.I)
_NICE_RE = re.compile(r'\bis a plus\b|\bnice.to.have\b|\bpreferred\b|\badvantage\b|\bdesirable\b|\bwelcome\b', re.I)

# Language detection
_DE_RE   = re.compile(r'\b(german|deutsch)\b', re.I)
_EN_RE   = re.compile(r'\b(english|englisch)\b', re.I)
_LANG_LEVEL_RE = re.compile(r'\b(fluent|verhandlungssicher|fließend|native|proficient|business)\b', re.I)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ParsedABBJob:
    job_db_id: int
    title: str
    # Extracted fields
    location: str = ""
    posted: str = ""
    end_date: str = ""
    job_id: str = ""
    role_bullets: list[str] = field(default_factory=list)
    qual_must: list[str] = field(default_factory=list)
    qual_nice: list[str] = field(default_factory=list)
    qual_other: list[str] = field(default_factory=list)
    language_required: str = "none"
    # Validation
    valid: bool = False
    missing: list[str] = field(default_factory=list)


# ── Core extraction ───────────────────────────────────────────────────────────

def _extract_bullets(block: str) -> list[str]:
    """Extract bullet points from a text block. Handles - and • prefixes."""
    bullets = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "*", "·")):
            bullets.append(line.lstrip("-•*· ").strip())
        elif len(line) > 20:  # Non-bullet but substantial line → include it
            bullets.append(line)
    return bullets


def _detect_language(bullets: list[str]) -> str:
    all_text = " ".join(bullets)
    de = bool(_DE_RE.search(all_text))
    en = bool(_EN_RE.search(all_text))
    if de and en:
        return "both_must"
    if de:
        return "german_must"
    if en:
        return "english_must"
    return "none"


def _classify_qual_bullet(bullet: str) -> str:
    if _MUST_RE.search(bullet):
        return "must"
    if _NICE_RE.search(bullet):
        return "nice"
    return "other"


def parse_abb_description(job_db_id: int, title: str, raw: str) -> ParsedABBJob:
    result = ParsedABBJob(job_db_id=job_db_id, title=title)
    missing = []

    # ── Meta fields ──────────────────────────────────────────────────────────
    m = _LOCATION_RE.search(raw)
    result.location = m.group(1).strip() if m else ""

    m = _POSTED_RE.search(raw)
    result.posted = m.group(1).strip() if m else ""

    m = _END_DATE_RE.search(raw)
    result.end_date = m.group(1).strip() if m else ""

    m = _JOB_ID_RE.search(raw)
    result.job_id = m.group(1).strip() if m else ""

    # ── Section anchors ──────────────────────────────────────────────────────
    role_idx = raw.find(_ROLE_ANCHOR)
    qual_idx = raw.find(_QUAL_ANCHOR)
    end_idx  = raw.find(_END_ANCHOR)

    has_role = role_idx != -1
    has_qual = qual_idx != -1
    has_end  = end_idx  != -1

    if not has_role:
        missing.append("role_section")
    if not has_qual:
        missing.append("qualifications_section")
    if not has_end:
        missing.append("more_about_us_section")

    # ── Role bullets ─────────────────────────────────────────────────────────
    if has_role:
        role_end = qual_idx if has_qual else (end_idx if has_end else len(raw))
        role_block = raw[role_idx + len(_ROLE_ANCHOR): role_end]
        result.role_bullets = _extract_bullets(role_block)
        if not result.role_bullets:
            missing.append("role_bullets_empty")

    # ── Qualification bullets ─────────────────────────────────────────────────
    if has_qual:
        qual_end = end_idx if has_end else len(raw)
        qual_block = raw[qual_idx + len(_QUAL_ANCHOR): qual_end]
        all_bullets = _extract_bullets(qual_block)
        for b in all_bullets:
            kind = _classify_qual_bullet(b)
            if kind == "must":
                result.qual_must.append(b)
            elif kind == "nice":
                result.qual_nice.append(b)
            else:
                result.qual_other.append(b)
        if not all_bullets:
            missing.append("qual_bullets_empty")
        result.language_required = _detect_language(all_bullets)

    result.missing = missing
    result.valid = len(missing) == 0
    return result


# ── Rendering ─────────────────────────────────────────────────────────────────

_LANG_LABELS = {
    "german_must":  "[DE required]",
    "english_must": "[EN required]",
    "both_must":    "[DE + EN required]",
    "german_nice":  "[DE preferred]",
    "english_nice": "[EN preferred]",
    "none":         "",
}

def render(job: ParsedABBJob) -> str:
    W = 80
    lines = []
    lines.append("=" * W)
    status = "[VALID]" if job.valid else f"[INVALID]  missing: {', '.join(job.missing)}"
    lines.append(f"  [{job.job_db_id}] {job.title}")
    lines.append(f"  {status}")
    lines.append("-" * W)

    meta = []
    if job.location: meta.append(f"📍 {job.location}")
    if job.end_date: meta.append(f"🗓  Ends {job.end_date}")
    if job.posted:   meta.append(f"⏱  {job.posted}")
    if job.job_id:   meta.append(f"🆔 {job.job_id}")
    lang = _LANG_LABELS.get(job.language_required, "")
    if lang:         meta.append(lang)
    if meta:
        lines.append("  " + "   |   ".join(meta))
        lines.append("-" * W)

    if job.role_bullets:
        lines.append("  What you'll do")
        for b in job.role_bullets:
            lines.append(f"    • {b}")
        lines.append("")

    has_qual = job.qual_must or job.qual_nice or job.qual_other
    if has_qual:
        lines.append("  Qualifications")
        if job.qual_must:
            lines.append("    -- Must have --")
            for b in job.qual_must:
                lines.append(f"    [+] {b}")
        if job.qual_nice:
            lines.append("    -- Nice to have --")
            for b in job.qual_nice:
                lines.append(f"    [o] {b}")
        if job.qual_other:
            lines.append("    -- Other --")
            for b in job.qual_other:
                lines.append(f"    [ ] {b}")

    lines.append("=" * W)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import sys
    out = open("scripts/abb_parser_output.txt", "w", encoding="utf-8")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    abb = conn.execute("SELECT id FROM companies WHERE name LIKE '%ABB%'").fetchone()
    if not abb:
        out.write("No ABB company found in DB.\n")
        return

    jobs = conn.execute(
        "SELECT id, title, description FROM jobs "
        "WHERE company_id=? AND description IS NOT NULL AND description != ''",
        (abb["id"],)
    ).fetchall()

    out.write(f"\nABB jobs with descriptions: {len(jobs)}\n\n")

    valid_count = 0
    invalid_count = 0
    invalid_reasons: dict[str, int] = {}

    for job in jobs:
        parsed = parse_abb_description(job["id"], job["title"], job["description"])
        out.write(render(parsed) + "\n\n")
        if parsed.valid:
            valid_count += 1
        else:
            invalid_count += 1
            for m in parsed.missing:
                invalid_reasons[m] = invalid_reasons.get(m, 0) + 1

    summary = [
        f"\nSummary: {valid_count} valid / {invalid_count} invalid / {len(jobs)} total",
        "\nInvalid reason breakdown:",
    ]
    for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
        summary.append(f"  {reason}: {count}")
    out.write("\n".join(summary) + "\n")
    out.close()
    conn.close()
    print(f"Done. Results written to scripts/abb_parser_output.txt")
    print(f"Summary: {valid_count} valid / {invalid_count} invalid / {len(jobs)} total")


if __name__ == "__main__":
    main()
