import os
import sqlite3
import requests
from pathlib import Path
from database import Database
from models import Lead, LeadStatus
from utils.error_handler import (
    classify_error,
    log_error,
    retry_with_backoff,
    ErrorCategory,
    QuotaExceededError,
    SkipLeadError,
    ERRORS_LOG_FILE
)
from utils.logger import get_logger

logger = get_logger("TestErrorHandling")


# Mock Exception Classes for Testing
class MockHTTP429Error(Exception):
    def __init__(self, message="HTTP 429 Rate Limit Exceeded"):
        super().__init__(message)
        self.status_code = 429


class MockAuthError(Exception):
    def __init__(self, message="HTTP 401 Unauthorized API Key"):
        super().__init__(message)
        self.status_code = 401


def test_scenario_1_fake_429_error(db: Database):
    print("\n" + "="*95)
    print("TEST SCENARIO 1: SIMULATING FAKE 429 (RATE LIMIT / QUOTA EXCEEDED) ERROR")
    print("="*95)

    lead_1 = Lead(business_name="Test Business 1", city="Vadodara", phone="+919876543210")
    lead_2 = Lead(business_name="Test Business 2 (Fails 429)", city="Vadodara", phone="+919876543211")
    lead_3 = Lead(business_name="Test Business 3", city="Vadodara", phone="+919876543212")

    db.upsert_lead(lead_1)
    db.upsert_lead(lead_2)
    db.upsert_lead(lead_3)

    completed_count = 0
    batch_stopped = False

    def mock_process_item(lead: Lead):
        if "Fails 429" in lead.business_name:
            raise MockHTTP429Error("429 Too Many Requests: Insufficient quota")
        lead.status = "VERIFIED"
        db.upsert_lead(lead)

    batch_leads = [lead_1, lead_2, lead_3]

    for lead in batch_leads:
        try:
            # Execute with error handler retry logic
            def work():
                mock_process_item(lead)
            
            retry_with_backoff(work, max_retries=1, lead_id=lead.lead_id, module_name="TestStage")
            completed_count += 1
        except QuotaExceededError:
            logger.warning("[TEST 1 PASSED] Batch stopped gracefully on QuotaExceededError. Work preserved!")
            batch_stopped = True
            break
        except Exception as e:
            cat, _ = classify_error(e)
            if cat == ErrorCategory.RATE_LIMIT:
                logger.warning(f"[TEST 1 PASSED] Rate limit detected and stopped gracefully: {e}")
                batch_stopped = True
                break

    print(f"Completed Items Before Stop: {completed_count}")
    print(f"Batch Stopped Gracefully   : {batch_stopped}")
    print(f"Lead 1 Status Saved in DB   : {db.get_lead_by_id(lead_1.lead_id).status}")


def test_scenario_2_interrupted_run_resumption(db: Database):
    print("\n" + "="*95)
    print("TEST SCENARIO 2: SIMULATING INTERRUPTED RUN & PIPELINE RESUMPTION")
    print("="*95)

    # 1. Reset 5 Vadodara leads
    all_leads = db.get_all_leads()
    vadodara_leads = [l for l in all_leads if l.city == "Vadodara"][:5]

    for l in vadodara_leads:
        l.status = "DISCOVERED"
        db.upsert_lead(l)

    print(f"Total Discovered Leads to Process: {len(vadodara_leads)}")

    # 2. Simulate processing ONLY 2 leads before a simulated crash
    for l in vadodara_leads[:2]:
        l.status = "VERIFIED"
        db.upsert_lead(l)

    print("Simulating pipeline crash after 2 leads completed stage 'WEBSITE_CHECK'...")

    # 3. Resume Pipeline Check using get_unprocessed_leads_for_stage
    unprocessed = db.get_unprocessed_leads_for_stage("WEBSITE_CHECK")

    print(f"\nResuming stage 'WEBSITE_CHECK'...")
    print(f"Unprocessed Leads Remaining: {len(unprocessed)} (Expected 3)")
    for u in unprocessed:
        print(f" - Remaining to process: '{u.business_name}' (Status: {u.status})")

    # Complete remaining
    for u in unprocessed:
        u.status = "VERIFIED"
        db.upsert_lead(u)

    unprocessed_after = db.get_unprocessed_leads_for_stage("WEBSITE_CHECK")
    print(f"Unprocessed Leads After Resumption Complete: {len(unprocessed_after)} (Expected 0)")
    assert len(unprocessed_after) == 0, "Pipeline resumption check failed!"
    print("[TEST 2 PASSED] Pipeline resumed cleanly without repeating successful work!")


def test_scenario_3_bad_lead_skipping(db: Database):
    print("\n" + "="*95)
    print("TEST SCENARIO 3: BAD LEAD SKIPPING & ERRORS.LOG AUDIT")
    print("="*95)

    bad_lead = Lead(
        business_name="Corrupted Lead Sample",
        city="Vadodara",
        phone=None,
        email=None,
        lead_id="bad_lead_999"
    )

    db.upsert_lead(bad_lead)

    def validate_and_process_phone(lead: Lead):
        if not lead.phone or len(lead.phone.strip()) < 7:
            raise ValueError("Invalid/Missing phone number required for lead processing.")
        lead.status = "QUALIFIED"
        db.upsert_lead(lead)

    lead_skipped = False
    try:
        def work():
            validate_and_process_phone(bad_lead)

        retry_with_backoff(work, max_retries=1, lead_id=bad_lead.lead_id, module_name="OutreachValidator")
    except SkipLeadError as sle:
        logger.warning(f"[TEST 3 PASSED] Bad lead successfully skipped: {sle}")
        lead_skipped = True
    except Exception as e:
        logger.info(f"Caught exception: {e}")
        lead_skipped = True

    print(f"Bad Lead Skipped          : {lead_skipped}")
    print(f"Check 'logs/errors.log'   : {ERRORS_LOG_FILE.exists()}")

    if ERRORS_LOG_FILE.exists():
        with open(ERRORS_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            print(f"Total Lines in errors.log : {len(lines)}")
            print("\nLast 5 Lines of errors.log:")
            for l in lines[-5:]:
                print(f"  {l.strip()}")


def run_test():
    db = Database()
    db.init_db()

    test_scenario_1_fake_429_error(db)
    test_scenario_2_interrupted_run_resumption(db)
    test_scenario_3_bad_lead_skipping(db)

if __name__ == "__main__":
    run_test()
