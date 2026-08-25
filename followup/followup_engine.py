import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from anthropic import Anthropic
from config import config
from database import Database
from models import Lead, LeadStatus
from approval.approval_queue import populate_approval_queue
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger
from utils.error_handler import retry_with_backoff, log_error

logger = get_logger("FollowupEngine")


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO timestamp string to timezone-aware datetime object."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def generate_followup_content(lead: Lead) -> Dict[str, str]:
    """
    Uses Anthropic Claude API to generate a fresh follow-up email and WhatsApp message.
    The message references the previous outreach, adds new value/question, and avoids repeating the original pitch.
    """
    if not config.ANTHROPIC_API_KEY:
        logger.warning(f"ANTHROPIC_API_KEY not set. Using template follow-up for '{lead.business_name}'.")
        return {
            "email_message": (
                f"Subject: Quick follow-up for {lead.business_name}\n\n"
                f"Hi {lead.business_name} team,\n\n"
                f"I wanted to quickly follow up on my previous note regarding the custom website preview I put together for {lead.business_name}.\n\n"
                f"Here is the preview link:\n"
                f"👉 {lead.demo_url}\n\n"
                f"Did you get a chance to take a look? Would love to answer any quick questions.\n\n"
                f"Best regards,\n{config.SENDER_NAME}"
            ),
            "whatsapp_message": (
                f"Hi {lead.business_name} team! Just following up on the website preview I shared earlier.\n\n"
                f"Here is the preview link:\n"
                f"👉 {lead.demo_url}\n\n"
                f"Did you get a chance to take a look?"
            )
        }

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    f_num = lead.followup_count + 1

    prompt = f"""
Business Name: {lead.business_name}
City: {lead.city or 'India'}
Category: {lead.category or 'Business'}
Website Status: {lead.website_status or 'NO_WEBSITE'}
Demo Preview URL: {lead.demo_url or 'http://localhost:8000/preview'}
Follow-up Number: #{f_num}

Instructions:
Generate follow-up outreach messages for this business in India:
1. Reference that this is a friendly follow-up regarding our earlier website concept preview.
2. DO NOT repeat the original pitch or exact wording.
3. Keep it brief, polite, human, and professional.
4. Email Subject line: MUST BE 3 to 5 words max (e.g. "Quick follow-up for {lead.business_name}"). ABSOLUTELY NO spam/hype/discount/offer/surprise words.
5. Email Body: Max 80 words.
6. WhatsApp: Max 50 words, casual and direct, ending with a simple question.

Format output exactly as:
---EMAIL---
Subject: <subject line>
<email body>
---WHATSAPP---
<whatsapp body>
"""

    try:
        def call_api():
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                system="You are a professional, polite web design consultant in India sending concise follow-up messages to local business owners. Never use hype, offer, discount, or surprise words. Keep subject lines 3-5 words max.",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text

        raw_output = call_api()
        parts = raw_output.split("---WHATSAPP---")
        email_part = parts[0].replace("---EMAIL---", "").strip() if len(parts) > 0 else ""
        wa_part = parts[1].strip() if len(parts) > 1 else ""

        return {
            "email_message": email_part,
            "whatsapp_message": wa_part
        }
    except Exception as e:
        logger.warning(f"Anthropic API call failed for '{lead.business_name}': {e}. Using intelligent fallback follow-up template.")
        return {
            "email_message": (
                f"Subject: Quick follow-up for {lead.business_name}\n\n"
                f"Hi {lead.business_name} team,\n\n"
                f"I'm following up on my previous message regarding the website concept we created for {lead.business_name}.\n\n"
                f"Have you had a chance to review the demo preview here: {lead.demo_url}?\n\n"
                f"I'd love to hear your feedback or answer any questions.\n\n"
                f"Best regards,\n{config.SENDER_NAME}"
            ),
            "whatsapp_message": (
                f"Hi {lead.business_name} team! Following up on the website preview I shared earlier:\n"
                f"👉 {lead.demo_url}\n\n"
                f"Did you get a chance to take a look? Would love to answer any quick questions!"
            )
        }


class FollowupEngine:
    """Manages follow-up lifecycle tracking, schedule calculations, message generation, and queueing."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.db.init_db()
        self.sheets_logger = GoogleSheetsLogger()

    def get_contacted_leads(self, force: bool = False) -> List[Lead]:
        """Fetches all leads that have been contacted initially or eligible for follow-ups."""
        if force:
            sql = "SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED', 'DEMO_READY', 'PERSONALIZED') OR email_status IN ('SENT', 'DRY_RUN_SENT');"
        else:
            sql = "SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED') OR email_status IN ('SENT', 'DRY_RUN_SENT');"
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [Lead.from_dict(dict(r)) for r in rows]

    def evaluate_and_process_followups(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        Evaluates all contacted leads against follow-up schedule rules:
        - Day 0: Initial message sent
        - Day 3: Follow-up 1
        - Day 7: Follow-up 2
        - Day 10+: Mark COLD if no reply after max follow-ups
        - force=True: Generates follow-up #1/#2 immediately for testing/demo.
        """
        contacted_leads = self.get_contacted_leads(force=force)
        if not contacted_leads:
            logger.info("No contacted leads found for follow-up evaluation.")
            return []

        now = datetime.now(timezone.utc)
        due_followups = []

        logger.info(f"Evaluating {len(contacted_leads)} contacted leads for follow-ups...")

        for lead in contacted_leads:
            # Skip Exclusion Rules
            if lead.status in (LeadStatus.REPLIED.value, LeadStatus.CONVERTED.value, LeadStatus.COLD.value, LeadStatus.DO_NOT_CONTACT.value, LeadStatus.REJECTED.value):
                continue
            if lead.approval_status in ("DO_NOT_CONTACT", "REJECTED"):
                continue

            last_time = parse_iso_datetime(lead.last_followup_at or lead.last_contacted_at or lead.updated_at or lead.created_at)
            if not last_time:
                continue

            days_passed = (now - last_time).days

            # Day 10+: Mark COLD if max follow-ups completed with no reply
            if days_passed >= 10 and lead.followup_count >= config.MAX_FOLLOWUPS:
                lead.status = LeadStatus.COLD.value
                self.db.upsert_lead(lead)
                self.sheets_logger.sync_lead(lead)
                logger.info(f"[FOLLOW-UP CYCLE CLOSED] Lead '{lead.business_name}' marked as COLD (No reply after {lead.followup_count} follow-ups).")
                continue

            # Check if Max Follow-ups Reached
            if lead.followup_count >= config.MAX_FOLLOWUPS:
                continue

            # Evaluate Schedule
            # Follow-up 1 due after FOLLOWUP_DAYS_STAGE1 (3 days)
            # Follow-up 2 due after FOLLOWUP_DAYS_STAGE2 (7 days total or 4 days after FU1)
            is_due = False
            target_fu_stage = lead.followup_count + 1

            if target_fu_stage == 1 and days_passed >= config.FOLLOWUP_DAYS_STAGE1:
                is_due = True
            elif target_fu_stage == 2 and days_passed >= config.FOLLOWUP_DAYS_STAGE2:
                is_due = True

            # FOR TESTING & DEMONSTRATION PURPOSE / FORCE MODE:
            if not is_due and (force or lead.status == "DRY_RUN_SENT") and lead.followup_count < config.MAX_FOLLOWUPS:
                is_due = True

            if is_due:
                due_followups.append(lead)

        if not due_followups:
            logger.info("No leads currently due for follow-ups.")
            return []

        logger.info(f"Found {len(due_followups)} leads DUE for follow-up message generation.")
        results = []

        for idx, lead in enumerate(due_followups, 1):
            logger.info(f"[{idx}/{len(due_followups)}] Generating Follow-up #{lead.followup_count + 1} for '{lead.business_name}'...")
            
            fu_content = generate_followup_content(lead)
            
            # Update lead message content for follow-up approval
            lead.email_message = fu_content["email_message"]
            lead.whatsapp_message = fu_content["whatsapp_message"]
            lead.followup_count += 1
            lead.last_followup_at = now.isoformat()
            lead.approval_status = "PENDING_APPROVAL"
            lead.status = LeadStatus.PENDING_APPROVAL.value

            self.db.upsert_lead(lead)
            self.sheets_logger.sync_lead(lead)

            # Queue follow-up into approvals table
            appr_record = {
                "approval_id": f"appr_fu_{lead.lead_id}_{lead.followup_count}",
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
                "notes": f"Follow-up #{lead.followup_count}"
            }
            self.db.upsert_approval(appr_record)

            logger.info(f"[FOLLOW-UP QUEUED] Follow-up #{lead.followup_count} generated and queued for approval for '{lead.business_name}'.")

            results.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "followup_count": lead.followup_count,
                "email_message": lead.email_message,
                "whatsapp_message": lead.whatsapp_message,
                "status": lead.status,
                "approval_status": lead.approval_status
            })

        return results
