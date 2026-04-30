"""Pre-compute level_tag, profile_tags, location_tags for jobs.

Called after every scrape and after description fetch.
Only processes jobs that are missing one or more tags (incremental).
"""
import json
import logging
import re
from typing import Optional

from .db import get_conn

logger = logging.getLogger(__name__)

# ── Level keywords ────────────────────────────────────────────────────────────
# Priority order: Management → Student Jobs → Entry → Associate → Senior → Mid Level → Others
# Mid Level requires matching a developer/engineer term AND not matching any higher-priority level.

_MGMT_KWS     = ['tech lead', 'team lead', 'head of', 'manager', 'director', 'vice president']
_MGMT_RE      = [r'\blead\b', r'\bvp\b']
_STUDENT_KWS  = ['werkstudent', 'working student', 'ausbildung', 'azubi', 'apprentice',
                 'duales studium', 'dual study', 'dualer student', 'praktikum', 'praktikant']
_STUDENT_RE   = [r'\bintern\b']
_ENTRY_KWS    = ['entry level', 'entry-level', 'graduate', 'berufseinsteiger']
_ENTRY_RE     = [r'\bjr\b']
_ASSOCIATE_KWS = ['junior']
_SENIOR_KWS   = ['senior', 'principal', 'staff engineer', 'architect', 'specialist', 'spezialist',
                 'fachkraft', 'software architect']
_SENIOR_RE    = [r'\bsr\b']
# Mid Level: generic developer/engineer titles — excluded if any senior/mgmt keyword present
_MID_KWS      = ['developer', 'entwickler', 'softwareentwickler', 'programmierer',
                 'engineer', 'system engineer', 'systems engineer']

# All senior-or-above signals used as exclusion guard for Mid Level
_SENIOR_GUARD_KWS = _SENIOR_KWS + _MGMT_KWS + _ASSOCIATE_KWS
_SENIOR_GUARD_RE  = _SENIOR_RE + _MGMT_RE + _ENTRY_RE + _STUDENT_RE


def _matches_any(title: str, kws: list, patterns: list) -> bool:
    for kw in kws:
        if kw in title:
            return True
    for pat in patterns:
        if re.search(pat, title):
            return True
    return False


def compute_level_tag(title: str) -> str:
    t = title.lower()
    if _matches_any(t, _MGMT_KWS, _MGMT_RE):
        return 'Management'
    if _matches_any(t, _STUDENT_KWS, _STUDENT_RE):
        return 'Student Jobs'
    if _matches_any(t, _ENTRY_KWS, _ENTRY_RE):
        return 'Entry'
    if _matches_any(t, _ASSOCIATE_KWS, []):
        return 'Associate'
    if _matches_any(t, _SENIOR_KWS, _SENIOR_RE):
        return 'Senior'
    # Mid Level: must match a dev/engineer term AND not have any senior/guard signal
    if _matches_any(t, _MID_KWS, []):
        if not _matches_any(t, _SENIOR_GUARD_KWS, _SENIOR_GUARD_RE):
            return 'Mid Level'
    return 'Others'


# ── Profile keywords ──────────────────────────────────────────────────────────
# Each profile: list of substrings to match in (title + description) lowercased.

_PROFILE_MAP: dict[str, list] = {
    'Software Developer': [
        'software developer', 'softwaredeveloper', 'software engineer', 'softwareengineer',
        'web developer', 'frontend developer', 'backend developer', 'fullstack', 'full stack',
        'full-stack', 'mobile developer', 'android developer', 'ios developer',
        'python developer', 'java developer', 'javascript developer', '.net developer',
        'c++ developer', 'rust developer', 'go developer', 'ruby developer',
        'php developer', 'kotlin developer', 'swift developer', 'typescript developer',
        'entwickler', 'softwareentwickler', 'programmierer',
    ],
    'Software Architect': [
        'software architect', 'solution architect', 'solutions architect',
        'enterprise architect', 'technical architect', 'cloud architect',
        'system architect', 'systems architect', 'it architect',
    ],
    'Test Engineer': [
        'test engineer', 'qa engineer', 'quality assurance engineer',
        'software tester', 'test automation', 'sdet', 'testingenieur',
        'tester', 'quality engineer', 'qa analyst',
    ],
    'Systems Engineer': [
        'systems engineer', 'system engineer', 'embedded engineer', 'embedded developer',
        'hardware engineer', 'firmware engineer', 'mechatronics', 'electrical engineer',
        'network engineer', 'infrastructure engineer',
    ],
    'Product Owner': [
        'product owner', 'product manager', 'produktmanager', 'po ', 'po/',
    ],
    'Scrum Master': [
        'scrum master', 'agile coach', 'scrum coach', 'agile master',
    ],
    'Quality Engineer': [
        'quality engineer', 'qualitätsingenieur', 'quality manager', 'qualitätsmanager',
        'quality assurance', 'qualitätssicherung', 'process engineer', 'prozessingenieur',
    ],
    'Project Manager': [
        'project manager', 'projektmanager', 'projektleiter', 'program manager',
        'it project manager', 'delivery manager',
    ],
    'DevOps / Cloud': [
        'devops', 'dev ops', 'site reliability', 'sre', 'platform engineer',
        'cloud engineer', 'cloud architect', 'kubernetes', 'infrastructure engineer',
        'deployment engineer', 'release engineer', 'ci/cd', 'mlops',
    ],
    'Data / ML / AI': [
        'data engineer', 'data scientist', 'machine learning', 'ml engineer',
        'ai engineer', 'deep learning', 'data analyst', 'analytics engineer',
        'nlp engineer', 'computer vision', 'data architect', 'bi developer',
        'business intelligence', 'big data',
    ],
}


def compute_profile_tags(title: str, description: str) -> list[str]:
    text = (title + ' ' + (description or '')).lower()
    return [profile for profile, kws in _PROFILE_MAP.items()
            if any(kw in text for kw in kws)]


# ── Location tags ─────────────────────────────────────────────────────────────

_VAGUE_LOC = re.compile(r'^\d+\s+locations?$', re.I)
_SPLIT = re.compile(r'[,/|;]|\bor\b|\band\b', re.I)
_REMOTE_RE = re.compile(r'\b(remote|homeoffice|home office|hybrid)\b', re.I)


def compute_location_tags(location: str) -> list[str]:
    if not location:
        return []
    if _VAGUE_LOC.match(location.strip()):
        return []
    parts = [p.strip() for p in _SPLIT.split(location) if p.strip()]
    tags = []
    seen = set()
    for part in parts:
        # Keep remote/hybrid as-is
        if _REMOTE_RE.search(part):
            label = 'Remote'
            if label not in seen:
                tags.append(label)
                seen.add(label)
            continue
        # Strip country suffixes like ", Germany" at end
        clean = re.sub(r',\s*\w+$', '', part).strip()
        if clean and clean not in seen:
            tags.append(clean)
            seen.add(clean)
    return tags


# ── DB helpers ────────────────────────────────────────────────────────────────

def tag_job(job_id: int, title: str, description: Optional[str], location: Optional[str]):
    level   = compute_level_tag(title)
    profiles = compute_profile_tags(title, description or '')
    locs    = compute_location_tags(location or '')
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET level_tag=?, profile_tags=?, location_tags=? WHERE id=?",
            (level, json.dumps(profiles), json.dumps(locs), job_id)
        )


def tag_untagged_jobs():
    """Tag all active jobs that are missing any tag. Safe to call repeatedly."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, title, description, location FROM jobs
            WHERE is_expired = 0
              AND (level_tag IS NULL OR profile_tags = '[]' OR location_tags IS NULL)
        """).fetchall()

    logger.info("Tagging %d untagged/partial jobs", len(rows))
    for row in rows:
        try:
            tag_job(row["id"], row["title"] or '', row["description"], row["location"])
        except Exception as e:
            logger.error("Failed to tag job %d: %s", row["id"], e)
    logger.info("Tagging complete")
