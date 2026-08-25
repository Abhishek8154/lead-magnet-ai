import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from config import config
from database import Database
from models import Lead, LeadStatus
from outreach.rate_limiter import rate_limiter
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger

logger = get_logger("EmailSender")


def can_send_email_to_lead(lead: Lead) -> Tuple[bool, str]:
    """Pre-send safety checks for email delivery."""
    if not lead.email or not str(lead.email).strip():
        return False, "Lead has no valid email address"
    if lead.approval_status != "APPROVED":
        return False, f"Approval status is '{lead.approval_status}' (must be APPROVED)"
    if lead.email_status == "SENT":
        return False, "Email has already been sent to this lead"
    if lead.status == "DO_NOT_CONTACT" or lead.approval_status == "DO_NOT_CONTACT":
        return False, "Lead is marked DO_NOT_CONTACT"
    if not rate_limiter.can_send_email():
        return False, "Hourly email rate limit exceeded"
    return True, "All pre-send safety checks passed"


def send_approved_emails(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None,
    delay_seconds: float = 3.0
) -> List[Dict[str, Any]]:
    """
    Sends cold emails to APPROVED leads.
    If config.DRY_RUN is True, prints preview and marks DRY_RUN_SENT without sending real emails.
    If config.DRY_RUN is False, connects to Gmail SMTP and dispatches emails.
    """
    if db is None:
        db = Database()
        db.init_db()

    sheets_logger = GoogleSheetsLogger()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [l for l in all_leads if l.approval_status == "APPROVED"]

    if not leads:
        logger.info("No APPROVED leads ready for email dispatch.")
        return []

    logger.info(f"Initiating email processing for {len(leads)} APPROVED leads (DRY_RUN={config.DRY_RUN})...")
    results = []

    for idx, lead in enumerate(leads, 1):
        can_send, reason = can_send_email_to_lead(lead)
        if not can_send:
            logger.warning(f"Skipping email for '{lead.business_name}': {reason}")
            if "no valid email" in reason.lower():
                lead.email_status = "NO_EMAIL"
                lead.error_log = "Skipped: Lead has no email address."
                db.upsert_lead(lead)
            continue

        now_iso = datetime.now(timezone.utc).isoformat()

        # Parse Email Subject & Body from lead.email_message
        msg_raw = lead.email_message or ""
        subject = f"Outreach for {lead.business_name}"
        body = msg_raw

        if msg_raw.startswith("Subject:"):
            parts = msg_raw.split("\n\n", 1)
            subject = parts[0].replace("Subject:", "").strip()
            body = parts[1] if len(parts) > 1 else ""

        # --- DRY RUN MODE ---
        if config.DRY_RUN:
            preview = body[:120].replace("\n", " ") + "..."
            print(f"\n[DRY RUN — EMAIL] Would send to {lead.business_name} ({lead.email}):\n  Subject: {subject}\n  Preview: {preview}")

            lead.email_status = "DRY_RUN_SENT"
            lead.status = LeadStatus.DRY_RUN_SENT.value
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            rate_limiter.record_email_sent()

            logger.info(f"[DRY RUN] Marked email status as DRY_RUN_SENT for '{lead.business_name}'.")
            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "email": lead.email,
                "email_status": lead.email_status,
                "status": lead.status,
                "mode": "DRY_RUN"
            })
            continue

        # --- REAL DISPATCH MODE (DRY_RUN = False) ---
        try:
            logger.info(f"Connecting to Gmail SMTP to send email to '{lead.business_name}' ({lead.email})...")
            
            # Setup MIME message
            mime_msg = MIMEMultipart()
            mime_msg["From"] = f"{config.SENDER_NAME} <{config.SENDER_EMAIL}>"
            mime_msg["To"] = lead.email
            mime_msg["Subject"] = subject
            mime_msg.attach(MIMEText(body, "plain", "utf-8"))

            # Connect via SMTP TLS (Port 587) or SSL (Port 465)
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
                server.starttls()
                server.login(config.SENDER_EMAIL, config.GMAIL_APP_PASSWORD)
                server.sendmail(config.SENDER_EMAIL, [lead.email], mime_msg.as_string())

            lead.email_status = "SENT"
            lead.last_contacted_at = now_iso
            lead.status = LeadStatus.SENT.value
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            rate_limiter.record_email_sent()

            logger.info(f"[EMAIL SENT SUCCESS] Email delivered to '{lead.business_name}' ({lead.email}).")
            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "email": lead.email,
                "email_status": lead.email_status,
                "sent_at": now_iso,
                "mode": "LIVE"
            })

        except Exception as e:
            err_msg = f"Failed to send email to '{lead.business_name}' ({lead.email}): {e}"
            logger.error(f"[EMAIL DISPATCH ERROR] {err_msg}")

            lead.email_status = "FAILED"
            lead.error_log = err_msg
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "email": lead.email,
                "email_status": lead.email_status,
                "error": err_msg,
                "mode": "LIVE"
            })

        # Add 3-second delay between emails
        if idx < len(leads):
            time.sleep(delay_seconds)

    return results
