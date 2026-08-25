import re
import httpx
from typing import List, Dict, Any, Optional
from fastapi.testclient import TestClient
from config import config
from database import Database
from models import Lead, LeadStatus
from demo.server import app, generate_slug
from utils.logger import get_logger

logger = get_logger("URLGenerator")


def process_demo_urls(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None,
    base_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generates personalized demo preview URLs for leads with status PERSONALIZED:
    - URL format: {DEMO_BASE_URL}/{slug}
    - Fallback: {DEMO_BASE_URL}?lead_id={lead_id}
    - Verifies page loading and business_name rendering via HTTP GET
    - Sets demo_status to READY / FAILED
    - Updates demo_url in DB and replaces {{DEMO_URL}} in outreach messages
    - Updates status to DEMO_READY
    """
    if db is None:
        db = Database()
        db.init_db()

    target_base = (base_url or config.DEMO_BASE_URL).rstrip("/")

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [l for l in all_leads if l.status == LeadStatus.PERSONALIZED.value]

    if not leads:
        logger.info("No leads with status PERSONALIZED found for demo URL generation.")
        return []

    logger.info(f"Starting demo URL generation and verification for {len(leads)} PERSONALIZED leads...")
    results = []

    # Initialize FastAPI TestClient for in-process HTTP verification
    test_client = TestClient(app)

    for idx, lead in enumerate(leads, 1):
        slug = generate_slug(lead.business_name, lead.city)
        demo_url = f"{target_base}/{slug}"
        fallback_url = f"{target_base}?lead_id={lead.lead_id}"

        logger.info(f"[{idx}/{len(leads)}] Generated slug '{slug}' for '{lead.business_name}'. URL: {demo_url}")

        # Verification via HTTP GET request
        verified = False
        try:
            # 1. Verify endpoint using FastAPI app test client
            endpoint_path = f"/preview/{slug}"
            response = test_client.get(endpoint_path)
            
            import html
            unescaped_html = html.unescape(response.text.lower())
            tokens = [t.lower() for t in lead.business_name.split() if len(t) > 2]
            name_matched = (lead.business_name.lower() in unescaped_html) or any(t in unescaped_html for t in tokens)

            if response.status_code == 200 and name_matched:
                verified = True
                logger.info(f"Demo URL HTTP verification PASSED for '{lead.business_name}' (200 OK & business name match).")
            else:
                logger.warning(
                    f"Demo URL HTTP verification FAILED for '{lead.business_name}'. "
                    f"Status Code: {response.status_code}, Name match: {name_matched}"
                )
        except Exception as e:
            logger.error(f"Error verifying demo URL for '{lead.business_name}': {e}")

        # Update Demo Status
        lead.demo_status = "READY" if verified else "FAILED"
        lead.demo_url = demo_url

        # Replace {{DEMO_URL}} and {DEMO_URL} placeholders in email and whatsapp messages
        from ai.personalizer import generate_fallback_messages
        fallback_msg = generate_fallback_messages(lead)

        if lead.email_message:
            lead.email_message = lead.email_message.replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
            if demo_url not in lead.email_message:
                lead.email_message += f"\n\n👉 View Your Custom Demo Here: {demo_url}"
        else:
            lead.email_message = f"Subject: {fallback_msg['email_subject']}\n\n{fallback_msg['email_body']}".replace("{{DEMO_URL}}", demo_url)

        if lead.whatsapp_message:
            lead.whatsapp_message = lead.whatsapp_message.replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
            if demo_url not in lead.whatsapp_message:
                lead.whatsapp_message += f"\n👉 {demo_url}"
        else:
            lead.whatsapp_message = fallback_msg['whatsapp_message'].replace("{{DEMO_URL}}", demo_url)


        # Advance lead status to DEMO_READY
        lead.status = LeadStatus.DEMO_READY.value

        db.upsert_lead(lead)
        logger.info(f"Updated lead '{lead.business_name}' status to DEMO_READY (demo_status: {lead.demo_status}).")

        results.append({
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "slug": slug,
            "demo_url": demo_url,
            "fallback_url": fallback_url,
            "demo_status": lead.demo_status,
            "status": lead.status,
            "email_message": lead.email_message,
            "whatsapp_message": lead.whatsapp_message
        })

    logger.info("Demo URL generation and verification batch completed.")
    return results
