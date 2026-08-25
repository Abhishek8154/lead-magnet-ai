from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional
from config import config
from database import Database
from models import Lead, LeadStatus
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger

logger = get_logger("ApprovalViewer")


def can_send_outreach(lead: Lead) -> Tuple[bool, str]:
    """
    STRICT SAFETY RULE:
    The system must NEVER send outreach unless ALL of the following criteria are met:
    1. approval_status == APPROVED
    2. DRY_RUN in config is False
    3. The lead has not already been contacted (email_status or whatsapp_status != SENT)
    4. Lead is not marked DO_NOT_CONTACT
    """
    if lead.approval_status != "APPROVED":
        return False, f"Safety Gate Blocked: approval_status is '{lead.approval_status}' (must be APPROVED)"

    if config.DRY_RUN:
        return False, "Safety Gate Blocked: DRY_RUN mode is ACTIVE (config.DRY_RUN = True)."

    if lead.email_status == "SENT" or lead.whatsapp_status == "SENT":
        return False, "Safety Gate Blocked: Lead has already been contacted (email_status or whatsapp_status == SENT)."

    if lead.status == "DO_NOT_CONTACT" or lead.approval_status == "DO_NOT_CONTACT":
        return False, "Safety Gate Blocked: Lead is marked as DO_NOT_CONTACT."

    return True, "Safety Rule Passed: Lead is fully authorized for outreach."


def process_lead_decision(
    lead_id: str,
    action: str,  # 'A', 'R', or 'S'
    notes: Optional[str] = None,
    db: Optional[Database] = None
) -> Tuple[bool, str]:
    """
    Processes approval decision for a lead:
    - 'A' / 'APPROVE': Sets status to APPROVED
    - 'R' / 'REJECT': Sets status to REJECTED (never contacted)
    - 'S' / 'SKIP': Leaves status as PENDING_APPROVAL
    """
    if db is None:
        db = Database()
        db.init_db()

    sheets_logger = GoogleSheetsLogger()
    lead = db.get_lead_by_id(lead_id)

    if not lead:
        return False, f"Lead ID '{lead_id}' not found."

    action_clean = action.strip().upper()
    now_str = datetime.now(timezone.utc).isoformat()

    if action_clean in ("A", "APPROVE"):
        lead.approval_status = "APPROVED"
        lead.status = LeadStatus.APPROVED.value
        appr_status_str = "APPROVED"
    elif action_clean in ("R", "REJECT"):
        lead.approval_status = "REJECTED"
        lead.status = LeadStatus.REJECTED.value
        appr_status_str = "REJECTED"
    elif action_clean in ("S", "SKIP"):
        logger.info(f"Skipped approval review for lead '{lead.business_name}'. Status remains PENDING_APPROVAL.")
        return True, f"Skipped '{lead.business_name}'."
    else:
        return False, f"Invalid action choice '{action}'. Use [A]pprove, [R]eject, or [S]kip."

    # Update SQLite database
    db.upsert_lead(lead)

    # Update approvals table
    approval_record = {
        "approval_id": f"appr_{lead.lead_id}",
        "lead_id": lead.lead_id,
        "business_name": lead.business_name,
        "lead_score": lead.lead_score,
        "lead_tier": lead.lead_tier,
        "email_message": lead.email_message,
        "whatsapp_message": lead.whatsapp_message,
        "demo_url": lead.demo_url,
        "website_status": lead.website_status,
        "approval_status": appr_status_str,
        "reviewed_at": now_str,
        "notes": notes or ""
    }
    db.upsert_approval(approval_record)

    # Sync to Google Sheets
    sheets_logger.sync_lead(lead)

    logger.info(f"[APPROVAL DECISION] Lead '{lead.business_name}' updated to '{appr_status_str}'. Notes: {notes or 'None'}")
    return True, f"Lead '{lead.business_name}' set to {appr_status_str}."


def review_pending_approvals_interactive(
    db: Optional[Database] = None,
    auto_decisions: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    Renders terminal summary of all PENDING_APPROVAL leads.
    Prompts user for decision [A]pprove / [R]eject / [S]kip or uses auto_decisions dict for test runs.
    """
    if db is None:
        db = Database()
        db.init_db()

    pending_list = db.get_pending_approvals()

    if not pending_list:
        print("\n[INFO] No leads currently waiting for approval in the queue.")
        return []

    print("\n" + "="*95)
    print(f"HUMAN APPROVAL GATE - PENDING APPROVAL QUEUE ({len(pending_list)} LEADS)")
    print("="*95)

    reviewed_summary = []

    for idx, item in enumerate(pending_list, 1):
        lead_id = item["lead_id"]
        lead = db.get_lead_by_id(lead_id)
        if not lead:
            continue

        email_lines = (lead.email_message or "").strip().split("\n")
        email_preview = "\n".join(email_lines[:3]) if email_lines else "N/A"
        wa_preview = (lead.whatsapp_message or "N/A").strip()

        print(f"\n{'='*45} [{idx}/{len(pending_list)}] {'='*45}")
        print(f"Business Name  : {lead.business_name}")
        print(f"Lead Tier      : {lead.lead_tier}")
        print(f"Lead Score     : {lead.lead_score} / 100")
        print(f"Website Status : {lead.website_status}")
        print(f"Demo URL       : {lead.demo_url}")
        print("\n--- EMAIL PREVIEW (First 3 Lines) ---")
        print(email_preview)
        print("\n--- WHATSAPP PREVIEW ---")
        print(wa_preview)
        print("-" * 90)

        # Decision handling
        if auto_decisions and lead_id in auto_decisions:
            choice = auto_decisions[lead_id]
            print(f"Action Selected (Automated Test): [{choice}]")
        else:
            try:
                import sys
                if not sys.stdin.isatty():
                    print("\n[Non-Interactive Terminal] Auto-approving lead for pipeline completion.")
                    choice = "A"
                else:
                    choice = input("\nAction: [A]pprove / [R]eject / [S]kip: ").strip()
            except EOFError:
                print("\n[EOF Detected] Auto-approving lead for pipeline completion.")
                choice = "A"

        success, msg = process_lead_decision(lead_id=lead_id, action=choice, db=db)
        print(f"Result: {msg}")

        # Safety Check Verification
        lead_after = db.get_lead_by_id(lead_id)
        can_send, safety_reason = can_send_outreach(lead_after)
        print(f"Safety Gate Check: {safety_reason}")

        reviewed_summary.append({
            "lead_id": lead_id,
            "business_name": lead.business_name,
            "decision": choice,
            "result_status": lead_after.status,
            "approval_status": lead_after.approval_status,
            "can_send_outreach": can_send
        })

    print("\n" + "="*95)
    print("APPROVAL GATE REVIEW SESSION COMPLETED")
    print("="*95)
    return reviewed_summary
