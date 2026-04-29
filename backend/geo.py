"""City-to-country resolution and location extraction from job descriptions."""
from __future__ import annotations
import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _build_lookup() -> dict[str, str]:
    """Build a lowercase city-name → country-name mapping."""
    try:
        import geonamescache
        gc = geonamescache.GeonamesCache()
        countries = gc.get_countries()          # {code: {name, ...}}
        cities    = gc.get_cities()             # {geonameid: {name, countrycode, ...}}
        code_to_name = {code: info["name"] for code, info in countries.items()}
        lookup: dict[str, str] = {}
        for city in cities.values():
            key = city["name"].lower()
            country = code_to_name.get(city["countrycode"], "")
            if country and key not in lookup:
                lookup[key] = country
        return lookup
    except Exception:
        return {}


_VAGUE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)


def resolve_country(location: str) -> str:
    """Return country name for a location string, or '' if unresolvable."""
    if not location:
        return ""
    loc = location.strip()
    if _VAGUE.match(loc):
        return ""
    lookup = _build_lookup()
    # Try progressively shorter tokens (handles "Munich, Bavaria, Germany" etc.)
    parts = [p.strip() for p in re.split(r"[,/|]", loc)]
    for part in parts:
        country = lookup.get(part.lower(), "")
        if country:
            return country
    return ""


def resolve_countries_for_jobs(job_ids_locations: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return [(job_id, country), ...] for a batch of (job_id, location) pairs."""
    return [(jid, resolve_country(loc)) for jid, loc in job_ids_locations]


# Keywords that appear near the top of job descriptions but are NOT city names
_NON_LOCATION = re.compile(
    r"^(vollzeit|teilzeit|festanstellung|befristet|praktikum|werkstudent|"
    r"internship|full.?time|part.?time|permanent|contract|remote|hybrid|"
    r"homeoffice|home office|onsite|on.?site|mobiles arbeiten|"
    r"anschreiben|schnelle bewerbung|berufserfahren|berufseinsteiger|"
    r"senior|junior|lead|principal|manager|engineer|developer|"
    r"apply|job details|overview|about|description|responsibilities|"
    r"karriere|careers|stellenangebot|stellenbeschreibung|"
    r"we are|we offer|your role|dein|ihre|unser).*",
    re.IGNORECASE,
)

_VAGUE_LOC = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)


def extract_location_from_description(title: str, description: str) -> str:
    """
    Attempt to extract a city name from the top of a job description.

    Most job portals repeat the title at the top, then show the city on a
    standalone line before employment-type metadata. We skip title-like lines
    and known non-location keywords, then take the first short remaining line
    that exists in our city lookup.
    """
    if not description:
        return ""

    lookup = _build_lookup()
    title_lower = (title or "").lower()

    # Only look in the first 30 non-empty lines — location is always near the top
    lines = [l.strip() for l in description.split("\n") if l.strip()][:30]

    for line in lines:
        # Skip blank, very long lines (paragraphs), or lines with digits (dates/codes)
        if len(line) > 60:
            continue
        words = line.split()
        if len(words) > 6:
            continue
        # Skip lines that look like the job title
        if title_lower and title_lower[:20] in line.lower():
            continue
        # Skip known non-location keywords
        if _NON_LOCATION.match(line):
            continue
        # Skip vague "X Locations" strings
        if _VAGUE_LOC.match(line):
            continue
        # Skip lines with brackets/slashes that look like title suffixes e.g. "(m/w/d)"
        if re.search(r"[()[\]/\\]", line):
            continue
        # Must exist in city lookup (case-insensitive)
        if line.lower() in lookup:
            return line

    return ""
