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
    If config.DRY_RUN is True, prints preview and marks DRY_RUN_SENT without API calls.
    If config.DRY_RUN is False, calls Meta WhatsApp Cloud API with retry on 429.
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
                lead.error_log = "Skipped: Lead has no valid phone number."
                db.upsert_lead(lead)
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        phone_formatted = format_whatsapp_phone(lead.phone)

        demo_link = lead.demo_url or ""
        if "trycloudflare.com" in demo_link or not demo_link:
            from demo.server import generate_slug
            slug = generate_slug(lead.business_name, lead.city)
            target_base = config.DEMO_BASE_URL.rstrip("/")
            demo_link = f"{target_base}/{slug}"
            lead.demo_url = demo_link

        msg_body = lead.whatsapp_message or f"Hi {lead.business_name}, check your demo here: {demo_link}"
        msg_body = msg_body.replace("{{DEMO_URL}}", demo_link).replace("{DEMO_URL}", demo_link)
        import re
        msg_body = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', demo_link, msg_body)
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
        phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID or ""
        token = config.WHATSAPP_TOKEN or ""

        if not phone_number_id or not token or phone_number_id == "YOUR_PHONE_NUMBER_ID":
            err_msg = "WHATSAPP_PHONE_NUMBER_ID or WHATSAPP_TOKEN is missing/default in .env"
            logger.error(f"[WHATSAPP ERROR] {err_msg}")
            lead.whatsapp_status = "FAILED"
            lead.error_log = "Automated WhatsApp API requires valid WHATSAPP_TOKEN & WHATSAPP_PHONE_NUMBER_ID in .env"
            db.upsert_lead(lead)
            results.append({"lead_id": lead.lead_id, "business_name": lead.business_name, "error": err_msg})
            continue

        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Primary payload: Text message
        text_payload = {
            "messaging_product": "whatsapp",
            "to": phone_formatted,
            "type": "text",
            "text": {"body": msg_body}
        }

        success = False
        err_msg = ""

        try:
            logger.info(f"[AUTOMATED WA DISPATCH] Calling Meta Cloud API for '{lead.business_name}' (+{phone_formatted})...")
            response = requests.post(url, headers=headers, json=text_payload, timeout=15)

            # Handle 429 Rate Limit - Wait 60s and retry ONCE
            if response.status_code == 429:
                logger.warning(f"[429 RATE LIMIT] Meta API rate limit hit for '{lead.business_name}'. Waiting 60s to retry...")
                time.sleep(60.0)
                response = requests.post(url, headers=headers, json=text_payload, timeout=15)

            if response.status_code in (200, 201):
                success = True
            else:
                resp_text = response.text
                # Fallback: Try Meta Template Payload if freeform text is restricted
                if "131047" in resp_text or "template" in resp_text.lower():
                    logger.info(f"Retrying Meta WhatsApp API with Template payload for '+{phone_formatted}'...")
                    template_payload = {
                        "messaging_product": "whatsapp",
                        "to": phone_formatted,
                        "type": "template",
                        "template": {
                            "name": os.getenv("WHATSAPP_TEMPLATE_NAME", "hello_world"),
                            "language": {"code": "en_US"}
                        }
                    }
                    tmpl_res = requests.post(url, headers=headers, json=template_payload, timeout=15)
                    if tmpl_res.status_code in (200, 201):
                        success = True
                    else:
                        err_msg = f"Meta API HTTP {tmpl_res.status_code}: {tmpl_res.text}"
                else:
                    if "GraphMethodException" in resp_text or "does not exist" in resp_text or "permissions" in resp_text:
                        err_msg = "Meta API Access Token or Phone Number ID expired/invalid in .env. Update credentials in developers.facebook.com."
                    else:
                        err_msg = f"Meta API HTTP {response.status_code}: {resp_text[:150]}"

        except Exception as e:
            err_msg = f"Network/API Exception: {e}"

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
            logger.error(f"[WHATSAPP DISPATCH FAILED] '{lead.business_name}': {err_msg}")
            lead.whatsapp_status = "FAILED"
            lead.error_log = err_msg
            db.upsert_lead(lead)
            sheets_logger.sync_lead(lead)

            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "phone": phone_formatted,
                "whatsapp_status": lead.whatsapp_status,
                "error": err_msg,
                "mode": "LIVE_AUTOMATED"
            })

            # ── AUTO EMAIL FALLBACK ──────────────────────────────────────────
            # If WhatsApp failed due to Meta test mode restriction (131030),
            # and this lead has an email, automatically send email instead.
            is_test_mode_block = any(code in err_msg for code in META_TEST_MODE_ERRORS)
            has_email = lead.email and str(lead.email).strip()
            email_not_yet_sent = lead.email_status not in ("SENT", "DRY_RUN_SENT")

            if is_test_mode_block and has_email and email_not_yet_sent:
                logger.info(f"[EMAIL FALLBACK] WhatsApp blocked by Meta test mode → Trying email for '{lead.business_name}'...")
                try:
                    from outreach.email_sender import send_approved_emails
                    fallback_results = send_approved_emails(leads=[lead], db=db)
                    if fallback_results and fallback_results[0].get("email_status") == "SENT":
                        logger.info(f"[EMAIL FALLBACK SUCCESS] Email sent to '{lead.business_name}' ({lead.email}).")
                    else:
                        logger.warning(f"[EMAIL FALLBACK] Email also failed for '{lead.business_name}'.")
                except Exception as fe:
                    logger.error(f"[EMAIL FALLBACK ERROR] Could not send email for '{lead.business_name}': {fe}")
            # ────────────────────────────────────────────────────────────────

    return results
