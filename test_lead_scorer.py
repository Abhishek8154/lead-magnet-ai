import json
from database import Database
from models import Lead, LeadStatus
from processing.lead_scorer import score_and_qualify_leads
from utils.logger import get_logger

logger = get_logger("TestLeadScorer")

def run_test():
    db = Database()
    db.init_db()

    # 1. Fetch Vadodara restaurant leads
    all_leads = db.get_all_leads()
    vadodara_leads = [l for l in all_leads if l.city == "Vadodara"]

    logger.info(f"Loaded {len(vadodara_leads)} Vadodara leads for scoring test.")

    # Temporarily set website_status variations on test leads to demonstrate scoring across tiers
    variations = [
        ("NO_WEBSITE", None),
        ("SOCIAL_ONLY", "https://instagram.com/candlelightvadodara"),
        ("DIRECTORY_ONLY", "https://justdial.com/vadodara/sakurapanasian"),
        ("BROKEN_WEBSITE", "http://broken-jassideparathe.com"),
        ("VALID_WEBSITE", "https://www.thehouseofmakeba.com/location/alkapuri-vadodara")
    ]

    for idx, lead in enumerate(vadodara_leads[:5]):
        ws, web_url = variations[idx]
        lead.status = LeadStatus.VERIFIED.value
        lead.website_status = ws
        if web_url is not None:
            lead.website_url = web_url
        db.upsert_lead(lead)

    # Re-fetch updated leads
    verified_leads = [l for l in db.get_all_leads() if l.status == LeadStatus.VERIFIED.value and l.city == "Vadodara"]

    # Run lead scoring
    results = score_and_qualify_leads(leads=verified_leads, db=db)

    print("\n" + "="*95)
    print("LEAD SCORING & QUALIFICATION RESULTS (VADODARA LEADS)")
    print("="*95)

    updated_leads = [l for l in db.get_all_leads() if l.city == "Vadodara"]

    for idx, lead in enumerate(updated_leads, 1):
        print(f"\n[{idx}] Business Name  : {lead.business_name}")
        print(f"    Category       : {lead.category}")
        print(f"    Website Status : {lead.website_status}")
        print(f"    Lead Score     : {lead.lead_score} / 100")
        print(f"    Lead Tier      : {lead.lead_tier}")
        print(f"    Status         : {lead.status}")
        print(f"    Reason         : {lead.qualification_reason}")

    print("\n" + "="*95)
    print("SCORING SUMMARY:")
    print("="*95)
    print(f"Total Scored: {len(results)}")
    for res in results:
        print(f" - {res['business_name']}: Score={res['lead_score']} | Tier={res['lead_tier']} | Status={res['status']}")

if __name__ == "__main__":
    run_test()
