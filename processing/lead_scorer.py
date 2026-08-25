import json
from typing import List, Dict, Any, Tuple, Optional
from models import Lead, LeadStatus
from database import Database
from utils.logger import get_logger

logger = get_logger("LeadScorer")

# Target commercial categories for lead qualification (+10 points)
TARGET_CATEGORY_KEYWORDS = ["restaurant", "hotel", "clinic", "salon", "gym", "shop", "dining", "bistro", "cafe"]


def calculate_lead_score(lead: Lead) -> Tuple[int, str, List[str]]:
    """
    Calculates lead score, assigns lead_tier, and generates qualification_reason list.
    Weights:
    Website signals:
    - NO_WEBSITE: +40
    - BROKEN_WEBSITE: +35
    - SOCIAL_ONLY: +30
    - DIRECTORY_ONLY: +28
    - DOMAIN_ONLY: +20
    - VALID_WEBSITE: +0
    Business signals:
    - Has phone number: +15
    - Has email: +10
    - Rating 4.0+ with 20+ reviews: +15
    - Rating 3.0-3.9 with reviews: +8
    - Has Instagram: +5
    - Category is restaurant/hotel/clinic/salon/gym/shop: +10

    Tiers:
    - Score 70+ = HOT
    - Score 45-69 = WARM
    - Score < 45 = LOW
    """
    score = 0
    reasons = []

    # 1. Website Signals
    ws = (lead.website_status or "").upper()
    if ws == "NO_WEBSITE":
        score += 40
        reasons.append("No Website (+40)")
    elif ws == "BROKEN_WEBSITE":
        score += 35
        reasons.append("Broken Website (+35)")
    elif ws == "SOCIAL_ONLY":
        score += 30
        reasons.append("Social Only (+30)")
    elif ws == "DIRECTORY_ONLY":
        score += 28
        reasons.append("Directory Only (+28)")
    elif ws == "DOMAIN_ONLY":
        score += 20
        reasons.append("Parked Domain (+20)")
    elif ws == "VALID_WEBSITE":
        reasons.append("Valid Website (+0)")

    # 2. Business Signals
    # Phone number (+15)
    if lead.phone and len(lead.phone.strip()) >= 7:
        score += 15
        reasons.append("Has Phone (+15)")

    # Email (+10)
    if lead.email and "@" in lead.email:
        score += 10
        reasons.append("Has Email (+10)")

    # Instagram (+5)
    if lead.instagram and lead.instagram.strip():
        score += 5
        reasons.append("Has Instagram (+5)")

    # Category (+10)
    category_str = (lead.category or "").lower()
    if any(keyword in category_str for keyword in TARGET_CATEGORY_KEYWORDS):
        score += 10
        reasons.append(f"Target Category '{lead.category}' (+10)")

    # Rating & Reviews Signal
    rating = None
    review_count = 0
    if lead.raw_data:
        try:
            raw_meta = json.loads(lead.raw_data)
            rating = raw_meta.get("rating")
            review_count = raw_meta.get("review_count") or 0
        except (json.JSONDecodeError, TypeError):
            pass

    if rating is not None:
        try:
            r_val = float(rating)
            rc_val = int(review_count) if review_count else 0

            if r_val >= 4.0 and rc_val >= 20:
                score += 15
                reasons.append(f"Rating {r_val}⭐ w/ {rc_val} reviews (+15)")
            elif 3.0 <= r_val <= 3.9 and rc_val > 0:
                score += 8
                reasons.append(f"Rating {r_val}⭐ w/ {rc_val} reviews (+8)")
        except ValueError:
            pass

    # 3. Tier Assignment
    if score >= 70:
        tier = "HOT"
    elif score >= 45:
        tier = "WARM"
    else:
        tier = "LOW"

    return score, tier, reasons


def score_and_qualify_leads(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None
) -> List[Dict[str, Any]]:
    """
    Scores every lead with status VERIFIED.
    Sets status to QUALIFIED for HOT and WARM leads.
    Saves lead_score, lead_tier, and qualification_reason to SQLite database.
    """
    if db is None:
        db = Database()
        db.init_db()

    if leads is None:
        all_leads = db.get_all_leads()
        leads = [l for l in all_leads if l.status == LeadStatus.VERIFIED.value]

    if not leads:
        logger.info("No leads with status VERIFIED found for scoring.")
        return []

    logger.info(f"Starting lead scoring and qualification for {len(leads)} VERIFIED leads...")
    results = []

    for lead in leads:
        score, tier, reasons = calculate_lead_score(lead)
        reason_str = ", ".join(reasons)

        lead.lead_score = score
        lead.lead_tier = tier
        lead.qualification_reason = reason_str

        # Update status to QUALIFIED for HOT & WARM leads
        if tier in ("HOT", "WARM"):
            lead.status = LeadStatus.QUALIFIED.value
            logger.info(f"[QUALIFIED {tier}] '{lead.business_name}' | Score: {score} | Reasons: {reason_str}")
        else:
            logger.info(f"[LOW TIER] '{lead.business_name}' | Score: {score} | Saved in DB, status unchanged.")

        db.upsert_lead(lead)

        results.append({
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "lead_score": score,
            "lead_tier": tier,
            "qualification_reason": reason_str,
            "status": lead.status
        })

    logger.info(f"Scoring completed for {len(leads)} leads.")
    return results
