import json
import sqlite3
from database import Database
from models import Lead, LeadStatus
from processing.deduplicate import process_and_deduplicate_leads
from processing.normalize import (
    normalize_business_name,
    normalize_phone,
    normalize_website,
    normalize_address
)
from utils.logger import get_logger

logger = get_logger("TestProcessing")

def clean_synthetic_data(db: Database):
    with db.get_connection() as conn:
        conn.cursor().execute("DELETE FROM leads WHERE lead_id = 'test_dup_jassi_123';")
        conn.commit()

def run_test():
    db = Database()
    db.init_db()

    # Clean previous synthetic test data if any
    clean_synthetic_data(db)

    # 1. Fetch 5 Vadodara leads from DB
    all_leads = db.get_all_leads()
    vadodara_leads = [l for l in all_leads if l.city == "Vadodara"]

    logger.info(f"Loaded {len(vadodara_leads)} original Vadodara leads.")

    # 2. Run normalization and quality scoring on the 5 leads
    process_and_deduplicate_leads(leads=vadodara_leads, db=db)

    # 3. Test adding a duplicate lead to verify duplicate detection rule
    dup_candidate = Lead(
        business_name="Jassi De Parathe Pvt Ltd",
        category="Punjabi Restaurant",
        city="Vadodara",
        phone="+91 99788 81313",  # Same phone as existing Jassi De Parathe
        address="Panorama Complex, 1, RC Dutt Rd, Opp Welcome Hotel, Alkapuri, Vadodara",
        website_url="https://www.jassideparathe.com/",
        status=LeadStatus.DISCOVERED.value,
        lead_id="test_dup_jassi_123"
    )
    
    # Process duplicate candidate
    dup_summary = process_and_deduplicate_leads(leads=[dup_candidate], db=db)

    # Clean synthetic test data after verification
    clean_synthetic_data(db)

    print("\n" + "="*90)
    print("VADODARA LEADS - NORMALIZATION & QUALITY SCORE BREAKDOWN")
    print("="*90)

    final_vadodara_leads = [l for l in db.get_all_leads() if l.city == "Vadodara"]

    for idx, lead in enumerate(final_vadodara_leads, 1):
        norm_name = normalize_business_name(lead.business_name)
        norm_ph = normalize_phone(lead.phone)
        norm_web = normalize_website(lead.website_url)
        norm_addr = normalize_address(lead.address)

        print(f"\n[{idx}] Business Name  : {lead.business_name}")
        print(f"    Normalized Name: {norm_name}")
        print(f"    Normalized Phone: {norm_ph}")
        print(f"    Normalized Web  : {norm_web}")
        print(f"    Address        : {lead.address}")
        print(f"    Quality Score  : {lead.quality_score} / 100")
        print(f"    Status         : {lead.status}")

    print("\n" + "="*90)
    print("DEDUPLICATION VERIFICATION TEST RESULTS:")
    print("="*90)
    print(f"Original Vadodara Leads Count : {len(final_vadodara_leads)}")
    print(f"Duplicate Candidate Test      : Detected as DUPLICATE = {dup_summary['results'][0]['is_duplicate']}")
    print(f"Duplicate Detection Reason    : {dup_summary['results'][0]['duplicate_reason']}")

if __name__ == "__main__":
    run_test()
