"""Load partner companies from partners.json into the DB."""
import json
from pathlib import Path

PARTNERS_PATH = Path(__file__).parent.parent / "partners.json"


def load_partners():
    if not PARTNERS_PATH.exists():
        return
    from .models import upsert_company
    partners = json.loads(PARTNERS_PATH.read_text())
    import json as _json
    for p in partners:
        upsert_company(
            p["name"], p["url"],
            fetch=p.get("fetch", "http"),
            method=p.get("method", "css"),
            job_link_selector=p.get("job_link_selector", ""),
            title_selector=p.get("title_selector", ""),
            pagination_json=_json.dumps(p.get("pagination", {})),
            api_body_json=_json.dumps(p.get("api_body", {})),
            job_base_url=p.get("job_base_url", ""),
            portal_url=p.get("portal_url", ""),
        )
