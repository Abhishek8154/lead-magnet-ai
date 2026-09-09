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


def get_stage_fallback_templates(lead: Lead, stage: int) -> Dict[str, str]:
    """Generates professional, courteous follow-up templates for healthcare practices (Day 3, 5, 7, and 10)."""
    biz_name = lead.business_name
    demo_link = lead.demo_url or "https://abhishek8154.github.io/lead-magnet-ai/preview"
    sender = config.SENDER_NAME or "Abhishek"

    if stage == 1:
        # Day 3: Courteous follow-up on demo preview
        return {
            "email_message": (
                f"Subject: Follow-up re: Digital Patient Experience for {biz_name}\n\n"
                f"Dear Dr. / {biz_name} Team,\n\n"
                f"I wanted to follow up briefly regarding the custom website and patient experience concept I shared earlier for {biz_name}.\n\n"
                f"You can review the interactive preview at your convenience:\n"
                f"👉 {demo_link}\n\n"
                f"Did you have an opportunity to review it? I would welcome the chance to answer any questions or adapt the layout to your clinic's specific requirements.\n\n"
                f"Sincerely,\n"
                f"{sender}\n"
                f"Healthcare Digital Strategy Consultant"
            ),
            "whatsapp_message": (
                f"Dear {biz_name} Team,\n\n"
                f"I am following up on the interactive website preview I shared for your clinic:\n"
                f"👉 {demo_link}\n\n"
                f"Did you get an opportunity to review the walkthrough? Please let me know if you have any questions or if you would like any customizations."
            )
        }
    elif stage == 2:
        # Day 5: Mobile patient booking & response time
        return {
            "email_message": (
                f"Subject: Mobile Patient Inquiries & Scheduling for {biz_name}\n\n"
                f"Dear Dr. / {biz_name} Team,\n\n"
                f"Studies show that over 80% of dental and healthcare searches in urban areas originate on smartphones. "
                f"In the digital concept we prepared for {biz_name}, we prioritized instant mobile loading, video tours, and one-touch appointment booking:\n\n"
                f"👉 {demo_link}\n\n"
                f"Would you be open to a brief 5-minute call this week to explore how this can help streamline your patient intake?\n\n"
                f"Sincerely,\n"
                f"{sender}\n"
                f"Healthcare Digital Strategy Consultant"
            ),
            "whatsapp_message": (
                f"Dear {biz_name} Team,\n\n"
                f"Quick note regarding {biz_name}'s online presence: over 80% of patients look for clinic details via mobile.\n\n"
                f"Our custom preview is engineered for instant mobile booking and patient reassurance:\n"
                f"👉 {demo_link}\n\n"
                f"Would you be available for a brief discussion this week?"
            )
        }
    elif stage == 3:
        # Day 7: Local clinic authority & patient trust
        return {
            "email_message": (
                f"Subject: Elevating Patient Trust & Online Visibility for {biz_name}\n\n"
                f"Dear Dr. / {biz_name} Team,\n\n"
                f"Maintaining a polished, high-authority digital presence is essential for building immediate credibility when prospective patients search for {lead.category or 'dental treatments'} in {lead.city or 'your city'}.\n\n"
                f"Your customized concept remains active here:\n"
                f"👉 {demo_link}\n\n"
                f"Please let me know if you would like our team to adjust the treatment highlights, clinician bios, or branding.\n\n"
                f"Sincerely,\n"
                f"{sender}\n"
                f"Healthcare Digital Strategy Consultant"
            ),
            "whatsapp_message": (
                f"Dear {biz_name} Team,\n\n"
                f"Following up regarding {biz_name}'s digital concept. A modern, interactive web portal helps convert local searches into confirmed patient appointments:\n\n"
                f"👉 {demo_link}\n\n"
                f"Please let me know if you would like us to tailor any sections for your clinic."
            )
        }
    else:
        # Day 10: Courteous closing note
        return {
            "email_message": (
                f"Subject: Final Follow-up: Archiving Digital Concept for {biz_name}\n\n"
                f"Dear Dr. / {biz_name} Team,\n\n"
                f"As I have not heard back from your team, I understand that updating your clinic's web presence may not be an immediate priority.\n\n"
                f"We will be archiving the custom interactive preview for {biz_name} at the end of the week:\n"
                f"👉 {demo_link}\n\n"
                f"Should you wish to keep the concept active or explore this in the future, please feel free to reach out anytime.\n\n"
                f"Wishing you and your practice continued success.\n\n"
                f"Sincerely,\n"
                f"{sender}\n"
                f"Healthcare Digital Strategy Consultant"
            ),
            "whatsapp_message": (
                f"Dear {biz_name} Team,\n\n"
                f"As we haven't connected, we will be archiving the custom website preview for {biz_name} soon:\n"
                f"👉 {demo_link}\n\n"
                f"If you would like to keep the preview active or discuss at a later date, please let us know anytime. Wishing your practice all the best!"
            )
        }


def generate_followup_content(lead: Lead) -> Dict[str, str]:
    """
    Uses Anthropic Claude API (or structured stage fallback) to generate
    stage-specific follow-ups (Stage 1: Day 3, Stage 2: Day 5, Stage 3: Day 7, Stage 4: Day 10).
    """
    f_num = min(lead.followup_count + 1, 4)

    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY.startswith("sk-ant-your"):
        return get_stage_fallback_templates(lead, f_num)

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    stage_contexts = {
        1: "Stage 1 (Day 3): Friendly check-in referencing the custom website concept preview.",
        2: "Stage 2 (Day 5): Highlighting mobile customer traffic and fast local Google discovery.",
        3: "Stage 3 (Day 7): Competitive advantage & customer trust angle for local clients in their city.",
        4: "Stage 4 (Day 10 - Final): Polite final closing note asking if they would like the demo concept archived."
    }

    prompt = f"""
Business Name: {lead.business_name}
City: {lead.city or 'India'}
Category: {lead.category or 'Business'}
Website Status: {lead.website_status or 'NO_WEBSITE'}
Demo Preview URL: {lead.demo_url or 'http://localhost:8000/preview'}
Follow-up Stage: #{f_num} - {stage_contexts.get(f_num, 'General Follow-up')}

Instructions:
Generate a stage-appropriate follow-up outreach message for this business in India:
1. Reference our earlier website concept preview without repeating the initial pitch.
2. Keep it brief, polite, human, and professional.
3. Email Subject: 3 to 5 words max. ABSOLUTELY NO spam/hype/discount/offer words.
4. Email Body: Max 80 words.
5. WhatsApp: Max 50 words, casual and direct, ending with a simple question.

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
                system="You are a polite, expert web design consultant sending concise follow-up messages to local business owners in India. Never use spammy or salesy language.",
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
        logger.warning(f"Anthropic API call fallback for '{lead.business_name}': {e}.")
        return get_stage_fallback_templates(lead, f_num)


class FollowupEngine:
    """Manages 4-stage follow-up lifecycle tracking (Day 3, 5, 7, 10), message generation, and dispatch."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.db.init_db()
        self.sheets_logger = GoogleSheetsLogger()

    def get_contacted_leads(self, force: bool = False) -> List[Lead]:
        """Fetches all leads that have been contacted initially or eligible for follow-ups."""
        if force:
            sql = "SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED', 'DEMO_READY', 'PERSONALIZED') OR email_status IN ('SENT', 'DRY_RUN_SENT');"
        else:
            sql = "SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED') OR email_status IN ('SENT', 'DRY_RUN_SENT') OR whatsapp_status IN ('SENT', 'WA_DIRECT_READY');"
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [Lead.from_dict(dict(r)) for r in rows]

    def evaluate_and_process_followups(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        Evaluates contacted leads against 4-stage follow-up schedule:
        - Day 0: Initial message sent
        - Day 3: Follow-up 1
        - Day 5: Follow-up 2
        - Day 7: Follow-up 3
        - Day 10: Follow-up 4 (Final note)
        - Day 12+: Mark COLD if no response after 4 follow-ups
        """
        contacted_leads = self.get_contacted_leads(force=force)
        if not contacted_leads:
            logger.info("No contacted leads found for follow-up evaluation.")
            return []

        now = datetime.now(timezone.utc)
        due_followups = []

        logger.info(f"Evaluating {len(contacted_leads)} contacted leads for follow-up schedule...")

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

            # Day 12+: Mark COLD if all 4 follow-ups completed with no reply
            if days_passed >= 12 and lead.followup_count >= config.MAX_FOLLOWUPS:
                lead.status = LeadStatus.COLD.value
                self.db.upsert_lead(lead)
                self.sheets_logger.sync_lead(lead)
                logger.info(f"[CYCLE CLOSED] Lead '{lead.business_name}' marked as COLD (No reply after {lead.followup_count} follow-ups).")
                continue

            # Check if Max Follow-ups Reached
            if lead.followup_count >= config.MAX_FOLLOWUPS:
                continue

            # 4-Stage Schedule Calculation:
            target_fu_stage = lead.followup_count + 1
            is_due = False

            if target_fu_stage == 1 and days_passed >= config.FOLLOWUP_DAYS_STAGE1:
                is_due = True
            elif target_fu_stage == 2 and days_passed >= config.FOLLOWUP_DAYS_STAGE2:
                is_due = True
            elif target_fu_stage == 3 and days_passed >= config.FOLLOWUP_DAYS_STAGE3:
                is_due = True
            elif target_fu_stage == 4 and days_passed >= config.FOLLOWUP_DAYS_STAGE4:
                is_due = True

            # Force mode for testing
            if not is_due and force and lead.followup_count < config.MAX_FOLLOWUPS:
                is_due = True

            if is_due:
                due_followups.append(lead)

        if not due_followups:
            logger.info("No leads currently due for follow-ups.")
            return []

        logger.info(f"Found {len(due_followups)} leads DUE for follow-up message generation.")
        results = []

        for idx, lead in enumerate(due_followups, 1):
            next_stage = lead.followup_count + 1
            logger.info(f"[{idx}/{len(due_followups)}] Generating Follow-up #{next_stage} for '{lead.business_name}'...")
            
            fu_content = generate_followup_content(lead)
            
            lead.email_message = fu_content["email_message"]
            lead.whatsapp_message = fu_content["whatsapp_message"]
            lead.followup_count = next_stage
            lead.last_followup_at = now.isoformat()
            lead.approval_status = "PENDING_APPROVAL"
            lead.status = LeadStatus.PENDING_APPROVAL.value

            self.db.upsert_lead(lead)
            self.sheets_logger.sync_lead(lead)

            # Record in approvals table
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
                "notes": f"Follow-up #{lead.followup_count} (Stage {lead.followup_count}/4)"
            }
            self.db.upsert_approval(appr_record)

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
