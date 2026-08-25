import json
from database import Database
from models import Lead, LeadStatus
from ai.personalizer import personalize_qualified_leads
from utils.logger import get_logger

logger = get_logger("TestPersonalizer")

def run_test():
    db = Database()
    db.init_db()

    # 1. Fetch Vadodara leads and set 3 HOT leads to QUALIFIED status for testing
    all_leads = db.get_all_leads()
    hot_leads = [l for l in all_leads if l.lead_tier == "HOT" or l.city == "Vadodara"][:3]

    logger.info(f"Preparing {len(hot_leads)} HOT leads for AI personalization test...")

    for lead in hot_leads:
        lead.status = LeadStatus.QUALIFIED.value
        if not lead.lead_tier:
            lead.lead_tier = "HOT"
        db.upsert_lead(lead)

    # 2. Execute personalization for the 3 HOT leads
    results = personalize_qualified_leads(leads=hot_leads, db=db, delay_seconds=0.5)

    print("\n" + "="*95)
    print("AI GENERATED OUTREACH MESSAGES (3 HOT LEADS)")
    print("="*95)

    for idx, res in enumerate(results, 1):
        print(f"\n{'='*40} [LEAD {idx}: {res['business_name']}] {'='*40}")
        print(f"Lead Tier      : {res['lead_tier']}")
        print(f"Website Status : {res['website_status']}")
        print(f"Status Updated : {res['status']}")
        print("\n--- COLD EMAIL ---")
        print(f"Subject: {res['email_subject']}")
        print("\nBody:")
        print(res['email_body'])
        print("\n--- WHATSAPP MESSAGE ---")
        print(res['whatsapp_message'])
        print("-" * 90)

    print("\n" + "="*95)
    print("PERSONALIZATION SUMMARY:")
    print("="*95)
    print(f"Total Leads Processed : {len(results)}")
    print("Status of all processed leads updated to: PERSONALIZED")

if __name__ == "__main__":
    run_test()
