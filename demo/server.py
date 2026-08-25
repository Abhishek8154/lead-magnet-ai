import sys
from pathlib import Path

# Add project root directory to sys.path so direct invocation works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import re
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from database import Database
from models import Lead
from utils.logger import get_logger

logger = get_logger("DemoServer")

# FastAPI App
app = FastAPI(title="Lead Magnet AI Demo Server")

# Setup Jinja2 Templates directory
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def generate_slug(business_name: str, city: Optional[str] = "") -> str:
    """
    Generates URL slug from business_name + city:
    - Lowercase
    - Strip special characters
    - Replace spaces with hyphens
    """
    b_name = (business_name or "").lower().strip()
    c_name = (city or "").lower().strip()

    combined = f"{b_name} {c_name}".strip()
    # Remove non-alphanumeric chars except space and hyphen
    clean_text = re.sub(r"[^\w\s-]", "", combined)
    # Convert spaces to hyphens
    slug = re.sub(r"[\s_]+", "-", clean_text)
    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def find_lead_by_slug_or_id(slug_or_id: str, db: Database) -> Optional[Lead]:
    """Finds lead by matching generated slug, lead_id, demo_url or normalized slug."""
    all_leads = db.get_all_leads()
    target = (slug_or_id or "").strip().lower()
    target_clean = re.sub(r"[^a-z0-9]", "", target)

    # 1. Exact match on candidate slug, lead_id, or demo_url suffix
    for lead in all_leads:
        candidate_slug = generate_slug(lead.business_name, lead.city).lower()
        if (candidate_slug == target or
            lead.lead_id.lower() == target or
            (lead.demo_url and lead.demo_url.lower().rstrip("/").endswith(target))):
            return lead

    # 2. Fuzzy match on normalized alphanumeric string
    for lead in all_leads:
        candidate_slug = generate_slug(lead.business_name, lead.city).lower()
        cand_clean = re.sub(r"[^a-z0-9]", "", candidate_slug)
        if cand_clean and (cand_clean == target_clean or cand_clean in target_clean or target_clean in cand_clean):
            return lead

    # 3. Fallback: match by business name tokens
    for lead in all_leads:
        b_name_clean = re.sub(r"[^a-z0-9]", "", lead.business_name.lower())
        if b_name_clean and len(b_name_clean) > 4 and (b_name_clean in target_clean or target_clean in b_name_clean):
            return lead

    return None


@app.get("/preview/{slug}", response_class=HTMLResponse)
async def preview_lead_page(request: Request, slug: str):
    """GET /preview/{slug} - Renders preview page for the lead."""
    db = Database()
    lead = find_lead_by_slug_or_id(slug, db)

    if not lead:
        logger.warning(f"Demo preview page requested for unknown slug: '{slug}'")
        raise HTTPException(status_code=404, detail=f"Preview page for '{slug}' not found.")

    # Parse rating from raw_data if available
    rating = None
    if lead.raw_data:
        try:
            raw_meta = json.loads(lead.raw_data)
            rating = raw_meta.get("rating")
        except (json.JSONDecodeError, TypeError):
            pass

    lead_dict = lead.to_dict()
    lead_dict["rating"] = rating

    logger.info(f"Rendering demo preview page for '{lead.business_name}' (Slug: {slug})")
    return templates.TemplateResponse("preview.html", {"request": request, "lead": lead_dict})


@app.get("/preview", response_class=HTMLResponse)
async def preview_fallback_page(request: Request, lead_id: Optional[str] = None):
    """GET /preview?lead_id={lead_id} - Fallback route."""
    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead_id query parameter.")

    db = Database()
    lead = db.get_lead_by_id(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead ID '{lead_id}' not found.")

    slug = generate_slug(lead.business_name, lead.city)
    return await preview_lead_page(request, slug)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
