import json
import requests
from typing import List, Dict, Any, Optional
from config import config
from database import Database
from models import Lead, LeadStatus, generate_lead_id
from utils.logger import get_logger

logger = get_logger("SerpApiDiscovery")


def discover_leads(
    city: str,
    business_type: str,
    max_results: int = 10,
    db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Searches Google Maps via SerpAPI for businesses matching business_type and city.
    Extracts business details, saves new leads to SQLite with status DISCOVERED,
    skips existing leads by lead_id check, handles HTTP 429/API errors gracefully,
    and returns a summary dictionary with raw response output and saved leads.
    """
    if db is None:
        db = Database()
        db.init_db()

    api_key = config.SERPAPI_KEY
    if not api_key or api_key == "your-serpapi-key":
        err_msg = "[Config Error] SERPAPI_KEY is missing or unconfigured in .env."
        logger.error(err_msg)
        print(f"ERROR: {err_msg}")
        return {"leads": [], "raw_output": {}, "error": err_msg}

    query = f"{business_type} in {city}"
    logger.info(f"Initiating SerpAPI Google Maps search for query: '{query}' (max_results={max_results})")

    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_maps",
        "q": query,
        "api_key": api_key,
        "type": "search"
    }

    try:
        response = requests.get(url, params=params, timeout=15)

        # Handle HTTP 429 Rate Limit - stop immediately
        if response.status_code == 429:
            err_msg = "[429 Rate Limit Exceeded] SerpAPI quota exceeded or rate limited. Stopping search immediately."
            logger.error(err_msg)
            print(f"ERROR: {err_msg}")
            return {"leads": [], "raw_output": {}, "error": err_msg}

        # Handle Auth / Key errors (401, 403)
        if response.status_code in (401, 403):
            err_msg = f"[{response.status_code} Auth Error] Invalid or unauthorized SerpAPI key."
            logger.error(err_msg)
            print(f"ERROR: {err_msg}")
            return {"leads": [], "raw_output": {}, "error": err_msg}

        response.raise_for_status()
        raw_data = response.json()

    except requests.exceptions.Timeout:
        err_msg = f"[Timeout Error] SerpAPI request timed out for query '{query}'."
        logger.error(err_msg)
        print(f"ERROR: {err_msg}")
        return {"leads": [], "raw_output": {}, "error": err_msg}
    except requests.exceptions.RequestException as e:
        err_msg = f"[Network Error] SerpAPI request failed: {e}"
        logger.error(err_msg)
        print(f"ERROR: {err_msg}")
        return {"leads": [], "raw_output": {}, "error": err_msg}

    # Check if API returned error in JSON response
    if "error" in raw_data:
        err_msg = f"[SerpAPI Error] {raw_data['error']}"
        logger.error(err_msg)
        print(f"ERROR: {err_msg}")
        return {"leads": [], "raw_output": raw_data, "error": err_msg}

    local_results = raw_data.get("local_results", [])
    if not local_results:
        logger.info(f"No local results returned from SerpAPI for query '{query}'.")
        return {"leads": [], "raw_output": raw_data, "error": None}

    saved_leads: List[Lead] = []
    skipped_count = 0

    for item in local_results[:max_results]:
        business_name = item.get("title") or item.get("name")
        if not business_name:
            continue

        category = item.get("type") or item.get("category")
        if not category and item.get("types"):
            types_val = item["types"]
            category = types_val[0] if isinstance(types_val, list) and types_val else str(types_val)

        phone = item.get("phone")
        address = item.get("address")
        website = item.get("website") or item.get("website_url")
        rating = item.get("rating")
        review_count = item.get("reviews") or item.get("review_count")
        google_maps_url = item.get("link") or item.get("place_id_search")
        source_url = item.get("place_id_search") or google_maps_url or url

        # Construct deterministic lead_id
        lead_id = generate_lead_id(business_name, city, phone or "")

        # Check if lead already exists in DB
        existing_lead = db.get_lead_by_id(lead_id)
        if existing_lead:
            logger.info(f"Skipping existing lead in DB: '{business_name}' (ID: {lead_id})")
            skipped_count += 1
            continue

        # Package raw details & rating info
        raw_info = {
            "rating": rating,
            "review_count": review_count,
            "google_maps_url": google_maps_url,
            "serpapi_item": item
        }

        lead = Lead(
            lead_id=lead_id,
            business_name=business_name,
            category=category,
            city=city,
            phone=phone,
            address=address,
            website_url=website,
            source_url=source_url,
            raw_data=json.dumps(raw_info),
            status=LeadStatus.DISCOVERED.value
        )

        db.upsert_lead(lead)
        saved_leads.append(lead)
        logger.info(
            f"Discovered and saved lead: '{business_name}' | Category: '{category}' | "
            f"Phone: '{phone}' | ID: {lead_id}"
        )

    logger.info(
        f"Discovery completed for '{query}': {len(saved_leads)} new leads saved, "
        f"{skipped_count} skipped (already in DB)."
    )

    return {
        "leads": saved_leads,
        "skipped_count": skipped_count,
        "raw_output": raw_data,
        "error": None
    }
