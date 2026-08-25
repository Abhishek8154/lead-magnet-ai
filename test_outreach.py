import json
from database import Database
from config import config
from models import Lead, LeadStatus
from outreach.email_sender import send_approved_emails, can_send_email_to_lead
from outreach.whatsapp_sender import send_approved_whatsapp_messages, can_send_whatsapp_to_lead
from utils.logger import get_logger

logger = get_logger("TestOutreach")

def run_test():
    db = Database()
    db.init_db()

    print("\n" + "="*95)
    print(f"OUTREACH DISPATCH ENGINE TEST (DRY_RUN = {config.DRY_RUN})")
    print("="*95)

    # 1. Fetch APPROVED leads from DB
    all_leads = db.get_all_leads()
    approved_leads = [l for l in all_leads if l.approval_status == "APPROVED"]

    logger.info(f"Loaded {len(approved_leads)} APPROVED leads for outreach test.")

    # Assign sample emails to test leads if missing
    for idx, lead in enumerate(approved_leads, 1):
        if not lead.email:
            lead.email = f"contact{idx}@vibesbistro.com"
            db.upsert_lead(lead)

    # 2. Run Email Outreach in DRY_RUN Mode
    print("\n--- EXECUTING EMAIL OUTREACH (DRY_RUN) ---")
    email_results = send_approved_emails(leads=approved_leads, db=db, delay_seconds=0.1)

    # 3. Run WhatsApp Outreach in DRY_RUN Mode
    print("\n--- EXECUTING WHATSAPP OUTREACH (DRY_RUN) ---")
    wa_results = send_approved_whatsapp_messages(leads=approved_leads, db=db)

    print("\n" + "="*95)
    print("SQLITE DATABASE VERIFICATION AFTER DRY RUN OUTREACH")
    print("="*95)

    updated_leads = [l for l in db.get_all_leads() if l.approval_status == "APPROVED"]

    for idx, lead in enumerate(updated_leads, 1):
        print(f"\n[{idx}] Business Name   : {lead.business_name}")
        print(f"    Email             : {lead.email}")
        print(f"    Phone             : {lead.phone}")
        print(f"    Approval Status   : {lead.approval_status}")
        print(f"    Email Status      : {lead.email_status}")
        print(f"    WhatsApp Status   : {lead.whatsapp_status}")
        print(f"    Lead Overall Status: {lead.status}")

    print("\n" + "="*95)
    print("SAFETY RULE ENFORCEMENT VERIFICATION ON REJECTED LEAD")
    print("="*95)
    rejected_leads = [l for l in db.get_all_leads() if l.approval_status == "REJECTED"]
    if rejected_leads:
        rej_lead = rejected_leads[0]
        can_email, reason_email = can_send_email_to_lead(rej_lead)
        can_wa, reason_wa = can_send_whatsapp_to_lead(rej_lead)
        print(f"Rejected Lead Name : {rej_lead.business_name}")
        print(f"Can Send Email?    : {can_email} (Reason: {reason_email})")
        print(f"Can Send WhatsApp? : {can_wa} (Reason: {reason_wa})")

if __name__ == "__main__":
    run_test()
