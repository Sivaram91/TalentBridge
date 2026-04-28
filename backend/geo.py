"""City-to-country resolution using geonamescache (offline, no API calls)."""
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
