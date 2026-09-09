import os
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from config import config
from database import Database
from models import Lead, LeadStatus
from processing.normalize import normalize_phone
from outreach.rate_limiter import rate_limiter
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger

logger = get_logger("WhatsAppSender")

# Error codes that mean Meta is in TEST MODE (not a token/config issue)
META_TEST_MODE_ERRORS = ["131030", "not in allowed list"]


def format_whatsapp_phone(phone: Optional[str]) -> str:
    """Formats phone number into international format with 91 country code for India."""
    raw_digits = normalize_phone(phone)
    if not raw_digits:
        return ""
    if len(raw_digits) == 10:
        return f"91{raw_digits}"
    return raw_digits


def can_send_whatsapp_to_lead(lead: Lead) -> Tuple[bool, str]:
    """Pre-send safety checks for WhatsApp delivery."""
    if not format_whatsapp_phone(lead.phone):
        return False, "Lead has no valid phone number"
    if lead.approval_status != "APPROVED":
        return False, f"Approval status is '{lead.approval_status}' (must be APPROVED)"
    if lead.whatsapp_status == "SENT":
        return False, "WhatsApp message has already been sent to this lead"
    if lead.status == "DO_NOT_CONTACT" or lead.approval_status == "DO_NOT_CONTACT":
        return False, "Lead is marked DO_NOT_CONTACT"
    if not rate_limiter.can_send_whatsapp():
        return False, "Hourly WhatsApp rate limit exceeded"
    return True, "All pre-send safety checks passed"


def send_approved_whatsapp_messages(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None
) -> List[Dict[str, Any]]:
    """
    Sends WhatsApp outreach to APPROVED leads.
    If config.DRY_RUN is True, marks DRY_RUN_SENT without sending real messages.
    If config.DRY_RUN is False, uses Linked WhatsApp Web session or Meta Cloud API.
    """
    if db is None:
        db = Database()
        db.init_db()

    sheets_logger = GoogleSheetsLogger()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [l for l in all_leads if l.approval_status == "APPROVED"]

    if not leads:
        logger.info("No APPROVED leads ready for WhatsApp dispatch.")
        return []

    logger.info(f"Initiating WhatsApp processing for {len(leads)} APPROVED leads (DRY_RUN={config.DRY_RUN})...")
    results = []

    for idx, lead in enumerate(leads, 1):
        can_send, reason = can_send_whatsapp_to_lead(lead)
        if not can_send:
            logger.warning(f"Skipping WhatsApp for '{lead.business_name}': {reason}")
            if "no valid phone" in reason.lower():
                lead.whatsapp_status = "NO_PHONE"
                db.upsert_lead(lead)
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        phone_formatted = format_whatsapp_phone(lead.phone)

        from demo.url_generator import get_permanent_demo_url
        demo_link = get_permanent_demo_url(lead.business_name, lead.city)
        lead.demo_url = demo_link

        # If lead has no stored message, generate a proper one
        if lead.whatsapp_message:
            msg_body = lead.whatsapp_message
        else:
            from ai.personalizer import generate_fallback_messages
            fallback = generate_fallback_messages(lead)
            msg_body = fallback['whatsapp_message']

        msg_body = msg_body.replace("{{DEMO_URL}}", demo_link).replace("{DEMO_URL}", demo_link)
        import re
        msg_body = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', demo_link, msg_body)
        msg_body = re.sub(r'https?://(?:localhost|127\.0\.0\.1):\d+/preview[^\s]*', demo_link, msg_body)
        if demo_link and demo_link not in msg_body:
            msg_body += f"\n👉 {demo_link}"

        # --- DRY RUN MODE ---
        if config.DRY_RUN:
            print(f"\n[DRY RUN — WHATSAPP] Would send to {lead.business_name} (+{phone_formatted}):\n  Message: {msg_body}")

            lead.whatsapp_status = "DRY_RUN_SENT"
            lead.status = LeadStatus.DRY_RUN_SENT.value
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            rate_limiter.record_whatsapp_sent()

            logger.info(f"[DRY RUN] Marked WhatsApp status as DRY_RUN_SENT for '{lead.business_name}'.")
            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "phone": phone_formatted,
                "whatsapp_status": lead.whatsapp_status,
                "status": lead.status,
                "mode": "DRY_RUN"
            })
            continue

        # --- REAL DISPATCH MODE (DRY_RUN = False) ---
        from outreach.whatsapp_web_sender import is_whatsapp_web_logged_in, send_whatsapp_message_automated

        success = False
        err_msg = ""
        is_session_issue = False

        # 1. Primary: Use Linked WhatsApp Web session
        if is_whatsapp_web_logged_in():
            logger.info(f"[AUTOMATED WA WEB DISPATCH] Using Linked WhatsApp Web Session for '{lead.business_name}' (+{phone_formatted})...")
            try:
                web_res = send_whatsapp_message_automated(phone=phone_formatted, message=msg_body)
                if web_res.get("status") == "SENT":
                    success = True
                else:
                    err_msg = web_res.get("error", "WhatsApp Web automated dispatch failed")
                    if web_res.get("status") in ("SESSION_EXPIRED", "FAILED"):
                        is_session_issue = True
            except Exception as we:
                err_msg = f"WhatsApp Web Exception: {we}"
                is_session_issue = True

        # 2. Secondary Fallback: Meta Cloud API (if configured and Web not linked)
        elif not is_whatsapp_web_logged_in():
            phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID or ""
            token = config.WHATSAPP_TOKEN or ""

            if not phone_number_id or not token or phone_number_id == "YOUR_PHONE_NUMBER_ID":
                err_msg = "WhatsApp Web not linked; ready for 1-Click WhatsApp dispatch."
                is_session_issue = True
                logger.info(f"[1-CLICK WA READY] {err_msg} for '{lead.business_name}'")
            else:
                url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                text_payload = {
                    "messaging_product": "whatsapp",
                    "to": phone_formatted,
                    "type": "text",
                    "text": {"body": msg_body}
                }
                try:
                    logger.info(f"[AUTOMATED WA DISPATCH] Calling Meta Cloud API for '{lead.business_name}' (+{phone_formatted})...")
                    response = requests.post(url, headers=headers, json=text_payload, timeout=15)
                    if response.status_code in (200, 201):
                        success = True
                    else:
                        resp_text = response.text
                        err_msg = f"Meta API HTTP {response.status_code}: {resp_text[:150]}"
                except Exception as e:
                    err_msg = f"Meta API Exception: {e}"

        if success:
            lead.whatsapp_status = "SENT"
            lead.last_contacted_at = now_iso
            lead.status = LeadStatus.SENT.value
            lead.error_log = None
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            rate_limiter.record_whatsapp_sent()

            logger.info(f"[WHATSAPP AUTOMATED DISPATCH SUCCESS] Delivered to '{lead.business_name}' (+{phone_formatted}).")
            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "phone": phone_formatted,
                "whatsapp_status": lead.whatsapp_status,
                "sent_at": now_iso,
                "mode": "LIVE_AUTOMATED"
            })
        else:
            # Fallback to 1-Click WhatsApp Direct Ready
            logger.warning(f"[WHATSAPP 1-CLICK READY] '{lead.business_name}' (+{phone_formatted}): {err_msg}")
            lead.whatsapp_status = "WA_DIRECT_READY"
            lead.error_log = None
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "phone": phone_formatted,
                "whatsapp_status": "WA_DIRECT_READY",
                "message": "Ready for 1-Click WhatsApp Dispatch",
                "mode": "1_CLICK_DIRECT"
            })

            # ── AUTO EMAIL FALLBACK IF AVAILABLE ──────────────────────────
            has_email = lead.email and str(lead.email).strip()
            email_not_yet_sent = lead.email_status not in ("SENT", "DRY_RUN_SENT")

            if has_email and email_not_yet_sent:
                logger.info(f"[EMAIL FALLBACK] Automated WhatsApp unavailable → Sending email for '{lead.business_name}'...")
                try:
                    from outreach.email_sender import send_approved_emails
                    fallback_results = send_approved_emails(leads=[lead], db=db)
                    if fallback_results and fallback_results[0].get("email_status") == "SENT":
                        logger.info(f"[EMAIL FALLBACK SUCCESS] Email sent to '{lead.business_name}' ({lead.email}).")
                    else:
                        logger.warning(f"[EMAIL FALLBACK] Email could not be delivered for '{lead.business_name}'.")
                except Exception as fe:
                    logger.error(f"[EMAIL FALLBACK ERROR] Could not send email for '{lead.business_name}': {fe}")
            # ────────────────────────────────────────────────────────────────

    return results
