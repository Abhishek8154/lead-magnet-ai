import re
import json
import time
import unicodedata
import anthropic
from typing import List, Dict, Any, Optional
from config import config
from database import Database
from models import Lead, LeadStatus
from utils.logger import get_logger

logger = get_logger("AIPersonalizer")

SYSTEM_PROMPT = (
    "You are an executive digital strategy & healthcare web design consultant in India. "
    "Generate highly professional, articulate, respectful B2B cold emails and WhatsApp messages for healthcare clinics and doctors. "
    "Tone: Professional, courteous, value-oriented, and credible. Never use casual slang, excessive exclamation points, or spammy claims. "
    "STRICTLY FORBIDDEN: Never use spam/hype/discount/offer/surprise/deal words (e.g. surprise, offer, discount, free, special, deal, sale, bonus). "
    "Ensure every message includes the {{DEMO_URL}} placeholder with clear call-to-action formatting."
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


def clean_business_name(raw_name: str) -> str:
    """
    Cleans Google Maps SEO keywords and clutter from business names.
    e.g. 'Dr. Rimmi Shekhawat's Marudhar Dental Centre - Dentist in Jaipur' -> 'Dr. Rimmi Shekhawat's Dental Centre'
    'Bangalore Dental Specialists Dental Clinic, Dentist HSR Layout' -> 'Bangalore Dental Specialists'
    """
    if not raw_name:
        return ""
    import unicodedata
    name = unicodedata.normalize('NFKD', raw_name)
    name = re.sub(r'[^\x00-\x7F]+', ' ', name)

    # Split by hyphen or pipe or comma to remove location/SEO suffixes
    parts = re.split(r'[-–—|,:]', name)
    main = parts[0].strip()

    # Clean redundant clinic/dentist descriptors
    main = re.sub(r'(?i)\b(best|top|expert|specialist|hospital|centre|center|ltd|pvt)\b', '', main)
    main = re.sub(r'\s+', ' ', main).strip()

    # Strip city name at end if preceded by space
    main = re.sub(r'(?i)\s+(Vadodara|Jaipur|Rajkot|Bangalore|Benglore|Bengaluru|Ahmedabad|Surat|Mumbai|Delhi|Austin|Hyderabad|Chennai|Pune)$', '', main).strip()

    main = re.sub(r'\s+', ' ', main).strip()
    if len(main) < 3:
        main = parts[0].strip()
    return main or raw_name.strip()


def generate_fallback_messages(lead: Lead) -> Dict[str, str]:
    """Generates professional, articulate, executive-level outreach messages for healthcare practices."""
    meta = extract_meta(lead)
    ws = (lead.website_status or "").upper()
    raw_b_name = lead.business_name
    b_name = clean_business_name(raw_b_name)
    city = lead.city or "your area"
    sender = config.SENDER_NAME or "Abhishek"

    if ws in ("NO_WEBSITE", "DOMAIN_ONLY", "SOCIAL_MEDIA_ONLY") or not lead.website_url:
        subject = f"Digital Patient Portal Concept for {b_name}"
        email_body_text = (
            f"Dear Dr. / {b_name} Team,\n\n"
            f"I hope this message finds you well.\n\n"
            f"While researching prominent dental practices in {city}, I noted that {b_name} does not currently have a dedicated website or online patient scheduling portal.\n\n"
            f"To illustrate how a modern digital presence can showcase your clinic's clinical expertise, patient video walkthroughs, and direct appointment bookings, I prepared a customized, interactive website preview for your practice:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"I would welcome your feedback on this concept. Would you or your practice manager be open to a brief 5-minute conversation this week to discuss how this could support your patient acquisition?\n\n"
            f"Sincerely,\n"
            f"{sender}\n"
            f"Healthcare Digital Strategy Consultant"
        )
        wa_text = (
            f"Dear {b_name} Team,\n\n"
            f"I hope you're having a productive week.\n\n"
            f"I noticed {b_name}'s strong reputation in {city} and put together a modern, interactive website concept to help showcase your clinical work and treatments to prospective patients:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Whenever you have a quick moment, take a look and let me know if this is something you'd like to explore for your practice.\n\n"
            f"Best regards,\n"
            f"{sender}"
        )

    elif ws == "BROKEN_WEBSITE":
        subject = f"Website Accessibility & Digital Concept for {b_name}"
        email_body_text = (
            f"Dear Dr. / {b_name} Team,\n\n"
            f"I hope this message finds you well.\n\n"
            f"While researching leading healthcare providers in {city}, I noticed that your clinic's current website appears temporarily inaccessible, which can prevent prospective patients from booking consultations.\n\n"
            f"I took the initiative to build a modern, interactive web concept tailored specifically for {b_name}—complete with video clinic tours, before-and-after smile transformation galleries, and streamlined appointment scheduling:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Please feel free to review the preview at your convenience. Would you be open to a brief conversation regarding restoring and upgrading your clinic's online presence?\n\n"
            f"Sincerely,\n"
            f"{sender}\n"
            f"Healthcare Digital Strategy Consultant"
        )
        wa_text = (
            f"Dear {b_name} Team,\n\n"
            f"I hope you're having a productive week.\n\n"
            f"I noticed {b_name}'s strong reputation in {city} and put together a modern, interactive website concept to help showcase your clinical work and treatments to prospective patients:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Whenever you have a quick moment, take a look and let me know if this is something you'd like to explore for your practice.\n\n"
            f"Best regards,\n"
            f"{sender}"
        )

    else:  # VALID_WEBSITE or Default
        subject = f"Interactive Patient Experience Concept for {b_name}"
        email_body_text = (
            f"Dear Dr. / {b_name} Team,\n\n"
            f"I hope this message finds you well.\n\n"
            f"While reviewing top-tier dental practices in {city}, I was impressed by the clinical reputation of {b_name}.\n\n"
            f"To explore ways to further elevate your patient engagement and increase direct appointment inquiries, I designed an interactive, mobile-optimized digital experience tailored to your practice:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"The concept includes interactive 3D video walkthroughs, smile transformation case studies, and instant consultation booking.\n\n"
            f"If you have a brief moment, I would welcome your thoughts. Would you be open to a brief discussion this week?\n\n"
            f"Sincerely,\n"
            f"{sender}\n"
            f"Healthcare Digital Strategy Consultant"
        )
        wa_text = (
            f"Dear {b_name} Team,\n\n"
            f"I hope you're having a productive week.\n\n"
            f"I noticed {b_name}'s strong reputation in {city} and put together a modern, interactive website concept to help showcase your clinical work and treatments to prospective patients:\n\n"
            f"👉 {{DEMO_URL}}\n\n"
            f"Whenever you have a quick moment, take a look and let me know if this is something you'd like to explore for your practice.\n\n"
            f"Best regards,\n"
            f"{sender}"
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
Generate an executive, professional, respectful B2B outreach message for a healthcare practice:

- Business Name: {lead.business_name}
- City: {lead.city or 'N/A'}
- Category: {lead.category or 'N/A'}
- Website Status: {lead.website_status or 'N/A'}
- Rating: {meta['rating'] or 'N/A'}

Tone & Formatting Rules:
1. Tone MUST be courteous, professional, and credible for doctors and practice directors.
2. Subject line: 4-6 words, formal (e.g. "Digital Patient Experience Concept for {lead.business_name}").
3. ABSOLUTELY NO spam, hype, or discount words (e.g., offer, discount, free, surprise, deal, bonus).
4. Email Body: Professional greeting ("Dear Dr. / Team"), polite value proposition, clear {{DEMO_URL}} call to action, professional closing and sign-off.
5. WhatsApp: Professional, concise, respectful greeting, clear {{DEMO_URL}}, polite call to action.

Return ONLY a valid JSON object with keys: "email_subject", "email_body", "whatsapp_message".
"""

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=12.0)
        # Try claude-3-7-sonnet or claude-3-5-sonnet model
        model_name = "claude-3-7-sonnet-20250219"
        
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
    Processes leads with status QUALIFIED.
    Generates cold email and WhatsApp messages using Claude / Anthropic SDK (or structured fallback).
    Saves email_message and whatsapp_message to SQLite DB and sets status to PERSONALIZED.
    """
    if db is None:
        db = Database()
        db.init_db()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [
            l for l in all_leads
            if l.status == LeadStatus.QUALIFIED.value or not l.email_message or not l.whatsapp_message or l.email_message == ""
        ]

    if not leads:
        logger.info("No QUALIFIED leads found for personalization.")
        return []

    logger.info(f"Starting AI personalization for {len(leads)} QUALIFIED leads...")
    results = []

    for idx, lead in enumerate(leads, 1):
        logger.info(f"[{idx}/{len(leads)}] Generating AI messages for '{lead.business_name}' (Tier: {lead.lead_tier}, WS: {lead.website_status})...")

        # Use Claude for HOT/WARM tier and fallback generator for LOW tier
        if lead.lead_tier in ("HOT", "WARM"):
            msg_data = call_anthropic_api(lead)
        else:
            msg_data = generate_fallback_messages(lead)

        full_email_message = f"Subject: {msg_data['email_subject']}\n\n{msg_data['email_body']}"
        full_wa_message = msg_data['whatsapp_message']
        
        # Always use permanent 24/7 HTTPS demo URL
        from demo.url_generator import get_permanent_demo_url
        target_demo_url = get_permanent_demo_url(lead.business_name, lead.city)
        lead.demo_url = target_demo_url

        full_email_message = full_email_message.replace("{{DEMO_URL}}", target_demo_url).replace("{DEMO_URL}", target_demo_url)
        full_email_message = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', target_demo_url, full_email_message)
        if target_demo_url not in full_email_message:
            full_email_message += f"\n\nHere is your custom website preview:\n👉 {target_demo_url}"

        full_wa_message = full_wa_message.replace("{{DEMO_URL}}", target_demo_url).replace("{DEMO_URL}", target_demo_url)
        full_wa_message = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', target_demo_url, full_wa_message)
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

        # Add 0.5s delay between calls for API requests
        if idx < len(leads) and lead.lead_tier in ("HOT", "WARM"):
            time.sleep(delay_seconds)

    logger.info("AI personalization completed.")
    return results
