import json
from database import Database
from models import Lead, LeadStatus
from processing.website_checker import verify_leads_websites
from utils.logger import get_logger

logger = get_logger("TestWebsiteChecker")

def run_test():
    db = Database()
    db.init_db()

    # Ensure Vadodara leads have status DISCOVERED so they are processed
    with db.get_connection() as conn:
        conn.cursor().execute("UPDATE leads SET status = 'DISCOVERED' WHERE city = 'Vadodara';")
        conn.commit()

    logger.info("Reset Vadodara leads status to DISCOVERED for website verification test.")

    # Process batch of 5 leads
    results = verify_leads_websites(batch_size=5, db=db, delay_seconds=1.0)

    print("\n" + "="*85)
    print("WEBSITE VERIFICATION RESULTS FOR VADODARA RESTAURANT LEADS")
    print("="*85)

    all_vadodara_leads = [l for l in db.get_all_leads() if l.city == "Vadodara"]

    for idx, lead in enumerate(all_vadodara_leads, 1):
        print(f"\n[{idx}] Business Name  : {lead.business_name}")
        print(f"    Website URL    : {lead.website_url}")
        print(f"    Website Status : {lead.website_status}")
        print(f"    Lead Status    : {lead.status}")

    print("\n" + "="*85)
    print("VERIFICATION BATCH SUMMARY:")
    print("="*85)
    print(f"Total Processed : {len(results)}")
    for res in results:
        print(f" - {res['business_name']}: {res['website_status']} ({res['website_url']})")

if __name__ == "__main__":
    run_test()
