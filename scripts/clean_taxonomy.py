"""
Remove non-skill noise from the skill_taxonomy_json setting.
Noise = HR/benefits terms, degrees, location names, company names,
        generic adjectives, vague one-word nouns with no technical meaning.
"""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend.db import get_conn

# ── Noise patterns (case-insensitive substring match) ─────────────────────────
# If ANY pattern matches, the skill is dropped.
NOISE_SUBSTRINGS = [
    # Benefits & HR
    "urlaub", "bonus", "kita", "work-life", "homeoffice", "hybrid",
    "mentoring", "coaching", "teamevents", "wellbeing", "mitarbeiter",
    "unternehmenskultur", "entwicklungsmöglich", "entwicklungsplan",
    "zuschüsse", "zusatzleistung", "altersmix", "teamgeist", "teilhabe",
    "kollegialität", "disziplin", "ownership", "integrity", "vision",
    "effizienz", "optimierung", "priorisierung", "anpassung",
    "nachverfolgung", "weiterentwicklung", "kommunikation",
    # Degrees & education
    "bachelor", "master", "bachelorstudium", "masterstudium",
    "b. eng.", "bsc", "msc", "b.eng", "m.eng", "diplom", "hochschule",
    "university degree", "studiengang", "mint-studiengang",
    "wirtschaftsingenieurwesen", "wirtschaftswissenschaften",
    "wirtschaftsinformatik", "wirtschafts-ingenieurwesen",
    "angewandte informatik", "ingenieurwesen", "ingenieurwissenschaften",
    "ingenieurmathematik", "naturwissenschaften", "physik/naturwissen",
    "bauingenieurwesen", "chemie", "wissenschaft",
    # Generic/vague single-word nouns
    "basiskompetenzen", "schlüsseltechnologien", "engineering background",
    "programmierkenntnisse", "edv-kenntnisse", "pc-anwenderkenntnisse",
    "it-bereich", "qualification", "qualifikation", "certification ",
    # Company-specific terms
    "abb global template", "abb procedures", "abb products", "abb systems",
    "abb's", "abf's", "business area/division", "working instructions",
    "working procedures", "business blueprint", "abb automation control",
    "sattline", "skywise", "softbank",
    # Locations
    "münchen", "moravskoslezsky", "côte atlantique",
    # Social media / marketing
    "instagram", "linkedin", "canva", "adobe indesign", "adobe photoshop",
    "social media plattformen", "content-aufbereitung", "cross media",
    "seo", "marketing",
    # Vague process words
    "digitalization", "digital solutions", "digital organization",
    "business value", "commercial negotiations", "contractual terms",
    "incoterms", "customs procedures", "eu trade compliance",
    "import/export", "tax regulations", "national and international standard",
    "contractual", "meilensteine", "erstellung", "documentation",
    "dokumentation", "arbeitsanweisungen", "arbeitsgestaltung",
    "arbeitsort", "arbeitszeiten", "strukturierte",
    # Bare acronyms with no context that are too ambiguous
]

# These exact full-string matches (lowercased) are noise — broad single-word generics
NOISE_EXACT_WORDS = {
    "automation", "automotive", "electrical", "electronics", "mechanical",
    "engineering", "software", "hardware", "science", "physics", "computer",
    "cabling", "normen", "standards", "guidelines", "sicherheit",
    "anforderungen", "telecommunication", "telekommunikation",
    "digitalization", "electrotechnik",
}

# Exact matches to always drop (case-insensitive) — ambiguous/non-technical acronyms only
NOISE_EXACT = {
    "ai", "ki", "api", "arm", "can", "ci", "cs", "crm", "din",
    "ecs", "emr", "b1", "b2", "c", "i", "mm", "sd", "rop",
    "ais", "alb", "amm", "asr", "asig", "cat a", "bms",
    "e/e", "ils", "mil", "mta", "puma", "rds", "rps", "rti",
    "tms", "wms", "vde", "vob", "pdm", "kpi", "roi",
    "rop", "rdp", "gti", "fds", "hts", "gmp", "hse",
    "paen", "esao",
}
NOISE_EXACT_LOWER = {s.lower() for s in NOISE_EXACT}

# Technical acronyms that are REAL skills — never drop these
KEEP_ACRONYMS = {
    "git", "sql", "html", "css", "vba", "bash", "php", "ada",
    "sap", "crm", "hmi", "plm", "uml", "sysml", "mbse", "tdd",
    "bdd", "obd", "rag", "llm", "iot", "ble", "nfc", "can",
    "spi", "i2c", "uart", "rest", "grpc", "mqtt", "opc",
    "osgi", "jpa", "tdd", "safe", "mvvm", "mvc", "orm",
    "hmi", "scada", "plc", "sps", "ecad", "pcb", "bsp", "hal",
    "rtos", "bsp", "xcp", "uds", "doip", "asil", "sil",
    "fmea", "fta", "fha", "hara", "apqp", "etap", "knx", "hvac",
    "abap", "erp", "sdk", "api", "ide", "svn", "pmp", "ipma",
    "itil", "lean", "kuka", "krl", "cnc", "hmi", "emc",
    "lin", "xcp", ".net", "qt", "dbus",
}

# Patterns: regex against the full skill string
NOISE_REGEX = [
    r'^\d+\s',              # starts with a number (e.g. "30 Tage Urlaub")
    r'rolling \d+',         # rolling demand forecasts
    r'sep qualifications',
    r'university degree',
    r'b\.\s?eng\.',
    r'automatyka$',
    r'villamosm',
    r'^bachelor',
    r'^master',
    r'^bachelorstudium',
    r'^masterstudium',
    r'degree in ',
    r'years of experience',
]

def is_noise(skill: str) -> bool:
    sl = skill.lower().strip()
    # Never drop known technical acronyms
    if sl in KEEP_ACRONYMS:
        return False
    if sl in NOISE_EXACT_LOWER:
        return True
    if sl in NOISE_EXACT_WORDS:
        return True
    for pat in NOISE_SUBSTRINGS:
        if pat in sl:
            return True
    for pat in NOISE_REGEX:
        if re.search(pat, skill, re.IGNORECASE):
            return True
    return False


def main():
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='skill_taxonomy_json'").fetchone()
        if not row:
            print("No taxonomy found.")
            return
        skills: list[str] = json.loads(row[0])

    print(f"Before: {len(skills)} skills")
    cleaned = [s for s in skills if not is_noise(s)]
    removed = [s for s in skills if is_noise(s)]
    print(f"After:  {len(cleaned)} skills  (removed {len(removed)})")
    print(f"\nRemoved ({len(removed)}):")
    for s in sorted(removed):
        print(f"  {s}")

    with get_conn() as conn:
        conn.execute(
            "UPDATE settings SET value=? WHERE key='skill_taxonomy_json'",
            (json.dumps(cleaned, ensure_ascii=False),)
        )
        conn.execute(
            "UPDATE settings SET value=? WHERE key='skill_taxonomy_count'",
            (str(len(cleaned)),)
        )
    print(f"\nDone — taxonomy updated to {len(cleaned)} skills.")


if __name__ == "__main__":
    main()
