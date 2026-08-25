import json
import time
import anthropic
from typing import List, Dict, Any, Optional
from config import config
from database import Database
from models import Lead, LeadStatus
from utils.logger import get_logger

logger = get_logger("AIPersonalizer")

SYSTEM_PROMPT = (
    "You are an elite, highly persuasive digital marketing & web design consultant in India. "
    "Generate ultra-attractive, engaging, high-converting cold emails and WhatsApp messages for business owners. "
    "Make messages feel like warm, genuine 1-on-1 personal compliments. Include subtle emojis. "
    "STRICTLY FORBIDDEN: Never use spam/hype/discount/offer/surprise/deal words (e.g. surprise, offer, discount, free, special, deal, sale, bonus). "
    "Ensure every message includes the {{DEMO_URL}} placeholder with clear call-to-action arrows."
)


def extract_meta(lead: Lead) -> Dict[str, Any]:
    """Extracts rating, review_count, instagram, and facebook from raw_data if available."""
    rating = None
    review_count = 0
    instagram = lead.instagram
    facebook = lead.facebook

    if lead.raw_data:
        try:
            raw_meta = json.loads(lead.raw_data)
            rating = raw_meta.get("rating")
            review_count = raw_meta.get("review_count") or 0
            if not instagram:
                instagram = raw_meta.get("instagram")
            if not facebook:
                facebook = raw_meta.get("facebook")
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "rating": rating,
        "review_count": review_count,
        "instagram": instagram,
        "facebook": facebook
    }


def generate_fallback_messages(lead: Lead) -> Dict[str, str]:
    """Generates attractive, high-converting personalized outreach messages tailored by website status."""
    meta = extract_meta(lead)
    ws = (lead.website_status or "").upper()
    b_name = lead.business_name
    city = lead.city or "your area"
    sender = config.SENDER_NAME or "Lead Magnet AI"

    rating_str = f" ⭐ ({meta['rating']} stars across {meta['review_count']} reviews)" if meta['rating'] else ""

    if ws == "NO_WEBSITE":
        subject = f"Personalized website concept for {b_name} 🚀"
        email_body_text = (
            f"Hi {b_name} Team,\n\n"
            f"I was searching for top-rated local businesses in {city} and was really impressed by {b_name}{rating_str}!\n\n"
            f"I noticed you don't currently have an official website to convert Google search traffic into direct customers. "
            f"To show you how much of a difference a modern web presence makes, I custom-designed an interactive website preview specifically for {b_name}:\n\n"
            f"👉 View Your Custom Demo Here: {{DEMO_URL}}\n\n"
            f"What's included in your preview:\n"
            f"• Premium Mobile-Optimized Interface\n"
            f"• Instant Direct Call & WhatsApp Booking Buttons\n"
            f"• High-Converting Service Showcase\n\n"
            f"Would you be open to a quick 2-minute chat this week to take a look?\n\n"
            f"Warm regards,\n{sender}\nLead Magnet AI Team"
        )
        wa_text = (
            f"Hey {b_name} Team! 👋\n\n"
            f"I was searching for top local businesses in {city} and was really impressed by {b_name}! ⭐\n\n"
            f"I noticed you don't have an official website yet, so I went ahead and built a custom interactive website preview specifically for your business:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"It's mobile-optimized and designed to capture direct client inquiries. Would love to get your thoughts when you have 2 minutes! 😊"
        )

    elif ws == "BROKEN_WEBSITE":
        subject = f"Quick update on {b_name}'s website + fresh demo 🌐"
        email_body_text = (
            f"Hi {b_name} Team,\n\n"
            f"I tried visiting your website while researching top-rated services in {city} and noticed your existing site appears to be unreachable or experiencing issues.\n\n"
            f"To help get your online presence back up and running smoothly, I put together a brand new interactive website concept tailored for {b_name}:\n\n"
            f"👉 View Your Fresh Preview Here: {{DEMO_URL}}\n\n"
            f"What's upgraded in your demo:\n"
            f"• Lightning-Fast Load Speeds & Secure Setup\n"
            f"• Modern Layout showcasing {b_name}'s key strengths\n"
            f"• Direct WhatsApp & Phone Inquiry Buttons\n\n"
            f"Would you have 2 minutes to take a quick look?\n\n"
            f"Warm regards,\n{sender}\nLead Magnet AI Team"
        )
        wa_text = (
            f"Hey {b_name} Team! 👋\n\n"
            f"I tried visiting your website while searching for top businesses in {city} and noticed it might be experiencing downtime.\n\n"
            f"To help get your business back online fast, I built a fresh, modern interactive website preview for {b_name}:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Take a quick look and let me know what you think! 😊"
        )

    elif ws == "SOCIAL_ONLY":
        subject = f"Elevating {b_name}'s online presence — custom demo inside ✨"
        email_body_text = (
            f"Hi {b_name} Team,\n\n"
            f"Loved seeing your active presence on social media! {b_name} clearly has a strong reputation in {city}{rating_str}.\n\n"
            f"A dedicated, high-converting website paired with your social media can help turn social profile visitors into direct, high-value paying customers. "
            f"I put together a custom interactive website demo designed for {b_name}:\n\n"
            f"👉 View Your Custom Demo Here: {{DEMO_URL}}\n\n"
            f"Key benefits built in:\n"
            f"• Seamless Integration with Your Social Media\n"
            f"• Direct Appointment & Booking Call-to-Actions\n"
            f"• Clean, Mobile-First Design\n\n"
            f"Could we connect for a quick 2-minute chat this week?\n\n"
            f"Warm regards,\n{sender}\nLead Magnet AI Team"
        )
        wa_text = (
            f"Hey {b_name} Team! 👋\n\n"
            f"Loved seeing {b_name}'s presence on social media! ⭐ A dedicated website will help convert your profile visitors into direct bookings.\n\n"
            f"I created a custom interactive website preview for {b_name}:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Would love to hear your feedback on the design when you take a look! 😊"
        )

    else:  # VALID_WEBSITE or Default
        subject = f"Quick website design concept for {b_name} 💡"
        email_body_text = (
            f"Hi {b_name} Team,\n\n"
            f"I came across {b_name} in {city} and was really impressed by your rating and reviews{rating_str}.\n\n"
            f"Upgrading your web experience with a modern, high-converting design can help double the leads you convert from online searches. "
            f"I custom-designed a fresh interactive website concept specifically for {b_name}:\n\n"
            f"👉 View Your Custom Demo Here: {{DEMO_URL}}\n\n"
            f"Key upgrades featured in your concept:\n"
            f"• Ultra-Fast Mobile Optimization\n"
            f"• One-Tap Direct WhatsApp & Call Booking\n"
            f"• Modern & Premium Visual Aesthetics\n\n"
            f"Would you be open to a 2-minute feedback chat this week?\n\n"
            f"Warm regards,\n{sender}\nLead Magnet AI Team"
        )
        wa_text = (
            f"Hey {b_name} Team! 👋\n\n"
            f"I came across {b_name} in {city} and was really impressed by your reviews and reputation! ⭐\n\n"
            f"I custom-designed a high-converting interactive website preview to show how you can boost your direct client inquiries:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Check it out and let me know your thoughts when you take a look! 😊"
        )

    return {
        "email_subject": subject,
        "email_body": email_body_text,
        "whatsapp_message": wa_text
    }


def call_anthropic_api(lead: Lead) -> Dict[str, str]:
    """
    Calls Anthropic Python SDK using model claude-sonnet-4-6 to generate personalized messages.
    Falls back gracefully if API key is invalid or request fails.
    """
    api_key = config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-your-key-here" or "your-key" in api_key:
        logger.warning(f"Anthropic API key is placeholder for lead '{lead.business_name}'. Using structured personalized fallback generator.")
        return generate_fallback_messages(lead)

    meta = extract_meta(lead)

    user_prompt = f"""
Generate ultra-personalized cold outreach messages for:

- Business Name: {lead.business_name}
- City: {lead.city or 'N/A'}
- Category: {lead.category or 'N/A'}
- Website Status: {lead.website_status or 'N/A'}
- Rating: {meta['rating'] or 'N/A'}

STRICT SUBJECT LINE RULES:
1. Subject line MUST BE EXACTLY 3 to 5 words long (e.g. "Quick question re: {lead.business_name}" or "Website concept for {lead.business_name}").
2. MUST feel like a genuine 1-on-1 personal email that makes the receiver curious and eager to open.
3. ABSOLUTELY NO SPAM OR HYPE WORDS: Never use words like "surprise", "offer", "discount", "free", "special", "deal", "bonus", "limited".

Email Body Rules:
- Max 80 words. Polite, concise, human. Include {{DEMO_URL}} placeholder.

WhatsApp Rules:
- Max 50 words. Direct & casual. Include {{DEMO_URL}} placeholder.

Return ONLY a valid JSON object with keys: "email_subject", "email_body", "whatsapp_message".
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Try claude-sonnet-4-6 or fallback model string
        model_name = "claude-sonnet-4-6"
        
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=600,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
        except Exception:
            # Fallback to standard Claude 3.7 / 3.5 model identifier if sonnet-4-6 alias is unavailable
            response = client.messages.create(
                model="claude-3-7-sonnet-20250219",
                max_tokens=600,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )

        content_text = response.content[0].text.strip()
        # Parse JSON
        if "```json" in content_text:
            content_text = content_text.split("```json")[1].split("```")[0].strip()
        elif "```" in content_text:
            content_text = content_text.split("```")[1].split("```")[0].strip()

        data = json.loads(content_text)
        return {
            "email_subject": data.get("email_subject", f"Web concept for {lead.business_name}"),
            "email_body": data.get("email_body", ""),
            "whatsapp_message": data.get("whatsapp_message", "")
        }

    except Exception as e:
        logger.error(f"Anthropic API call failed for '{lead.business_name}': {e}. Using fallback template generator.")
        return generate_fallback_messages(lead)


def personalize_qualified_leads(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None,
    delay_seconds: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Processes leads with status QUALIFIED (HOT or WARM tier only).
    Generates cold email and WhatsApp messages using Claude / Anthropic SDK.
    Saves email_message and whatsapp_message to SQLite DB and sets status to PERSONALIZED.
    """
    if db is None:
        db = Database()
        db.init_db()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [
            l for l in all_leads
            if not l.email_message or not l.whatsapp_message or l.email_message == ""
        ]

    if not leads:
        logger.info("No QUALIFIED (HOT/WARM) leads found for personalization.")
        return []

    logger.info(f"Starting AI personalization for {len(leads)} QUALIFIED leads...")
    results = []

    for idx, lead in enumerate(leads, 1):
        logger.info(f"[{idx}/{len(leads)}] Generating AI messages for '{lead.business_name}' (Tier: {lead.lead_tier}, WS: {lead.website_status})...")

        msg_data = call_anthropic_api(lead)

        full_email_message = f"Subject: {msg_data['email_subject']}\n\n{msg_data['email_body']}"
        full_wa_message = msg_data['whatsapp_message']
        
        # If demo_url exists or can be constructed, replace placeholder immediately
        target_demo_url = lead.demo_url
        if not target_demo_url:
            from demo.server import generate_slug
            slug = generate_slug(lead.business_name, lead.city)
            target_demo_url = f"{config.DEMO_BASE_URL}/{slug}"

        if target_demo_url:
            full_email_message = full_email_message.replace("{{DEMO_URL}}", f" {target_demo_url} ").replace("{DEMO_URL}", f" {target_demo_url} ")
            if target_demo_url not in full_email_message:
                full_email_message += f"\n\nHere is your custom website preview:\n👉 {target_demo_url}"
            full_wa_message = full_wa_message.replace("{{DEMO_URL}}", f" {target_demo_url} ").replace("{DEMO_URL}", f" {target_demo_url} ")
            if target_demo_url not in full_wa_message:
                full_wa_message += f"\n👉 {target_demo_url}"

        lead.email_message = full_email_message
        lead.whatsapp_message = full_wa_message
        lead.status = LeadStatus.PERSONALIZED.value


        db.upsert_lead(lead)
        logger.info(f"Successfully generated messages & updated status to PERSONALIZED for '{lead.business_name}'.")

        results.append({
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "lead_tier": lead.lead_tier,
            "website_status": lead.website_status,
            "email_subject": msg_data['email_subject'],
            "email_body": msg_data['email_body'],
            "whatsapp_message": msg_data['whatsapp_message'],
            "status": lead.status
        })

        # Add 0.5s delay between calls
        if idx < len(leads):
            time.sleep(delay_seconds)

    logger.info("AI personalization completed.")
    return results
