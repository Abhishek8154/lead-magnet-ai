from typing import List, Dict, Any, Optional
from database import Database
from models import Lead, LeadStatus
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger

logger = get_logger("ApprovalQueue")


def populate_approval_queue(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None
) -> List[Dict[str, Any]]:
    """
    Moves every lead with status PERSONALIZED or DEMO_READY and demo_status = READY
    into the approval queue in the 'approvals' SQLite table.
    Sets approval_status = 'PENDING_APPROVAL' and lead status = 'PENDING_APPROVAL'.
    Syncs changes to SQLite and Google Sheets.
    """
    if db is None:
        db = Database()
        db.init_db()

    sheets_logger = GoogleSheetsLogger()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [
            l for l in all_leads
            if l.status in (LeadStatus.PERSONALIZED.value, LeadStatus.DEMO_READY.value)
            and l.demo_status == "READY"
        ]

    if not leads:
        logger.info("No leads ready to move to approval queue.")
        return []

    logger.info(f"Populating approval queue for {len(leads)} leads...")
    queued_records = []

    for lead in leads:
        approval_id = f"appr_{lead.lead_id}"
        approval_record = {
            "approval_id": approval_id,
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "lead_score": lead.lead_score,
            "lead_tier": lead.lead_tier,
            "email_message": lead.email_message,
            "whatsapp_message": lead.whatsapp_message,
            "demo_url": lead.demo_url,
            "website_status": lead.website_status,
            "approval_status": "PENDING_APPROVAL",
            "reviewed_at": None,
            "notes": None
        }

        # Save to approvals table
        db.upsert_approval(approval_record)

        # Update lead object
        lead.approval_status = "PENDING_APPROVAL"
        lead.status = LeadStatus.PENDING_APPROVAL.value
        db.upsert_lead(lead)

        # Sync to Google Sheets
        sheets_logger.sync_lead(lead)

        logger.info(f"[QUEUED FOR APPROVAL] '{lead.business_name}' (ID: {lead.lead_id}) | Approval ID: {approval_id}")

        queued_records.append(approval_record)

    logger.info(f"Approval queue populated with {len(queued_records)} records.")
    return queued_records
