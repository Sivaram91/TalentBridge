"""Load partner companies from partners.json into the DB."""
import json
from pathlib import Path

PARTNERS_PATH = Path(__file__).parent.parent / "partners.json"


def load_partners():
    if not PARTNERS_PATH.exists():
        return
    from .models import upsert_company
    partners = json.loads(PARTNERS_PATH.read_text())
    for p in partners:
        upsert_company(p["name"], p["url"])
