import json
from database import Database
from models import Lead, LeadStatus
from approval.approval_queue import populate_approval_queue
from approval.approval_viewer import review_pending_approvals_interactive, can_send_outreach
from utils.logger import get_logger

logger = get_logger("TestApprovalGate")

def run_test():
    db = Database()
    db.init_db()

    # 1. Prepare 5 Vadodara restaurant leads in PERSONALIZED / DEMO_READY status
    all_leads = db.get_all_leads()
    vadodara_leads = [l for l in all_leads if l.city == "Vadodara"][:5]

    logger.info(f"Loaded {len(vadodara_leads)} Vadodara restaurant leads for approval test...")

    for lead in vadodara_leads:
        lead.status = LeadStatus.DEMO_READY.value
        lead.demo_status = "READY"
        lead.approval_status = "PENDING"
        db.upsert_lead(lead)

    # 2. Populate Approval Queue (moves leads into 'approvals' table with status PENDING_APPROVAL)
    queued = populate_approval_queue(leads=vadodara_leads, db=db)
    logger.info(f"Populated approval queue with {len(queued)} records.")

    # 3. Simulate human review choices:
    # Lead 1 -> Approve ('A')
    # Lead 2 -> Approve ('A')
    # Lead 3 -> Reject  ('R')
    # Lead 4 -> Approve ('A')
    # Lead 5 -> Skip    ('S')
    auto_decisions = {
        vadodara_leads[0].lead_id: "A",
        vadodara_leads[1].lead_id: "A",
        vadodara_leads[2].lead_id: "R",
        vadodara_leads[3].lead_id: "A",
        vadodara_leads[4].lead_id: "S"
    }

    # Run review session
    review_results = review_pending_approvals_interactive(db=db, auto_decisions=auto_decisions)

    print("\n" + "="*95)
    print("SQLITE DATABASE VERIFICATION FOR LEADS AND APPROVALS")
    print("="*95)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT approval_id, lead_id, business_name, approval_status, reviewed_at FROM approvals;")
        approval_rows = [dict(r) for r in cursor.fetchall()]

        print("\n--- 'approvals' Table Records in SQLite ---")
        for r in approval_rows:
            print(f"Approval ID: {r['approval_id']} | Name: {r['business_name']} | Status: {r['approval_status']} | Reviewed At: {r['reviewed_at']}")

        cursor.execute("SELECT lead_id, business_name, status, approval_status FROM leads WHERE city = 'Vadodara';")
        lead_rows = [dict(r) for r in cursor.fetchall()]

        print("\n--- 'leads' Table Records in SQLite ---")
        for r in lead_rows:
            print(f"Lead ID: {r['lead_id']} | Name: {r['business_name']} | Status: {r['status']} | Approval Status: {r['approval_status']}")

    print("\n" + "="*95)
    print("SAFETY RULE VERIFICATION DEMONSTRATION")
    print("="*95)
    approved_lead = db.get_lead_by_id(vadodara_leads[0].lead_id)
    can_send, reason = can_send_outreach(approved_lead)
    print(f"Test Approved Lead Outreach Clearance: {can_send} (Reason: {reason})")

if __name__ == "__main__":
    run_test()
