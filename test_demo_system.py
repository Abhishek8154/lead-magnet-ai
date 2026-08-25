import json
from fastapi.testclient import TestClient
from database import Database
from models import Lead, LeadStatus
from demo.url_generator import process_demo_urls
from demo.server import app, generate_slug
from utils.logger import get_logger

logger = get_logger("TestDemoSystem")

def run_test():
    db = Database()
    db.init_db()

    # 1. Fetch leads with status PERSONALIZED or set 3 leads to PERSONALIZED for testing
    all_leads = db.get_all_leads()
    test_leads = [l for l in all_leads if l.city == "Vadodara"][:3]

    logger.info(f"Loaded {len(test_leads)} leads for Demo URL system test...")

    for lead in test_leads:
        lead.status = LeadStatus.PERSONALIZED.value
        db.upsert_lead(lead)

    # 2. Run Demo URL generation and verification
    results = process_demo_urls(leads=test_leads, db=db, base_url="http://localhost:8000/preview")

    print("\n" + "="*95)
    print("DEMO PREVIEW URL GENERATION & VERIFICATION RESULTS")
    print("="*95)

    for idx, res in enumerate(results, 1):
        print(f"\n[{idx}] Business Name  : {res['business_name']}")
        print(f"    Slug           : {res['slug']}")
        print(f"    Generated URL  : {res['demo_url']}")
        print(f"    Fallback URL   : {res['fallback_url']}")
        print(f"    Demo Status    : {res['demo_status']}")
        print(f"    Lead Status    : {res['status']}")
        print("\n    Updated Cold Email (Sample):")
        email_preview = (res['email_message'] or '').split('\n\n')[0] + "\n" + (res['email_message'] or '').split('\n\n')[1] if res['email_message'] else ''
        print(f"    {email_preview}")
        print("\n    Updated WhatsApp Message:")
        print(f"    {res['whatsapp_message']}")

    # 3. Fetch rendered HTML output for Lead #1
    test_client = TestClient(app)
    slug = results[0]['slug']
    html_response = test_client.get(f"/preview/{slug}")

    print("\n" + "="*95)
    print(f"RENDERED HTML PAGE OUTPUT FOR SLUG: '/preview/{slug}'")
    print("="*95)
    print(html_response.text[:1500])  # Print top 1500 characters of rendered HTML page
    print("\n... [HTML Output Truncated for Display] ...")

if __name__ == "__main__":
    run_test()
