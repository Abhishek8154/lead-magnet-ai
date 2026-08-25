from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple, Optional
from models import Lead, LeadStatus
from database import Database
from processing.normalize import (
    normalize_business_name,
    normalize_phone,
    normalize_website,
    normalize_address,
    calculate_quality_score
)
from utils.logger import get_logger

logger = get_logger("Deduplication")


def string_similarity(str1: str, str2: str) -> float:
    """Computes similarity ratio between two strings (0.0 to 1.0)."""
    if not str1 or not str2:
        return 0.0
    return SequenceMatcher(None, str1, str2).ratio()


def check_duplicate_pair(lead1: Lead, lead2: Lead) -> Tuple[bool, Optional[str]]:
    """
    Compares lead1 (candidate) against lead2 (existing reference).
    Returns (is_duplicate: bool, reason: str).
    Rule: Does NOT merge different branches (same name, different address = keep both).
    """
    # 0. Primary Key Match
    if lead1.lead_id == lead2.lead_id:
        return True, f"Exact lead_id match ({lead1.lead_id})"

    norm_name1 = normalize_business_name(lead1.business_name)
    norm_name2 = normalize_business_name(lead2.business_name)

    norm_phone1 = normalize_phone(lead1.phone)
    norm_phone2 = normalize_phone(lead2.phone)

    norm_web1 = normalize_website(lead1.website_url)
    norm_web2 = normalize_website(lead2.website_url)

    norm_addr1 = normalize_address(lead1.address)
    norm_addr2 = normalize_address(lead2.address)

    # Helper: check if addresses indicate different branches
    is_different_branch = False
    if norm_addr1 and norm_addr2:
        addr_sim = string_similarity(norm_addr1, norm_addr2)
        if addr_sim < 0.4:
            is_different_branch = True

    # 1. Phone Match
    if norm_phone1 and norm_phone2 and norm_phone1 == norm_phone2:
        if is_different_branch:
            logger.info(
                f"Same phone ({norm_phone1}) but different addresses detected for '{lead1.business_name}' vs '{lead2.business_name}'. Keeping as separate branches."
            )
        else:
            return True, f"Matching phone number ({norm_phone1})"

    # 2. Website Match
    if norm_web1 and norm_web2 and norm_web1 == norm_web2:
        if is_different_branch and string_similarity(norm_name1, norm_name2) < 0.7:
            logger.info(
                f"Same domain ({norm_web1}) but different addresses/names for '{lead1.business_name}'. Keeping separate."
            )
        else:
            return True, f"Matching website domain ({norm_web1})"

    # 3. Business Name Similarity + Address Match
    if norm_name1 and norm_name2:
        name_sim = string_similarity(norm_name1, norm_name2)
        if name_sim >= 0.85:
            if is_different_branch:
                logger.info(
                    f"Same name similarity ({name_sim:.2f}) but distinct addresses. Keeping as separate branches: '{lead1.business_name}' and '{lead2.business_name}'."
                )
            else:
                if norm_addr1 and norm_addr2:
                    addr_sim = string_similarity(norm_addr1, norm_addr2)
                    return True, f"High name similarity ({name_sim:.2%}) and address match ({addr_sim:.2%})"
                else:
                    city1 = (lead1.city or "").lower().strip()
                    city2 = (lead2.city or "").lower().strip()
                    if city1 and city2 and city1 == city2:
                        return True, f"High name similarity ({name_sim:.2%}) in same city ({lead1.city})"

    return False, None


def process_and_deduplicate_leads(
    leads: Optional[List[Lead]] = None,
    db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Processes leads:
    1. Calculates and assigns quality_score to each lead.
    2. Compares leads against existing database records to mark duplicates.
    3. Updates database records with status DUPLICATE and quality_score.
    """
    if db is None:
        db = Database()
        db.init_db()

    if leads is None:
        leads = db.get_all_leads()

    existing_leads = db.get_all_leads()
    processed_results = []
    duplicate_count = 0
    unique_count = 0

    logger.info(f"Starting normalization, quality scoring, and deduplication for {len(leads)} leads...")

    for lead in leads:
        # Calculate Quality Score (0 - 100)
        q_score = calculate_quality_score(lead)
        lead.quality_score = q_score
        lead.lead_score = q_score  # Update lead_score as well
        if q_score >= 70:
            lead.lead_tier = "HOT"
        elif q_score >= 45:
            lead.lead_tier = "WARM"
        else:
            lead.lead_tier = "LOW"

        is_dup = False
        dup_reason = None

        # Compare against existing database records (excluding itself by lead_id)
        for existing in existing_leads:
            if existing.lead_id == lead.lead_id and existing.status == LeadStatus.DUPLICATE.value:
                continue

            # Compare if not the exact same record in DB
            if existing.lead_id != lead.lead_id:
                matched, reason = check_duplicate_pair(lead, existing)
                if matched:
                    is_dup = True
                    dup_reason = f"Duplicate of '{existing.business_name}' (ID: {existing.lead_id}) - Reason: {reason}"
                    break

        if is_dup:
            duplicate_count += 1
            lead.status = LeadStatus.DUPLICATE.value
            lead.error_log = dup_reason
            db.upsert_lead(lead)
            logger.warning(f"[DUPLICATE DETECTED] Lead '{lead.business_name}' (ID: {lead.lead_id}) marked as DUPLICATE. Reason: {dup_reason}")
        else:
            unique_count += 1
            if lead.status == LeadStatus.DUPLICATE.value:
                lead.status = LeadStatus.DISCOVERED.value
                lead.error_log = None
            db.upsert_lead(lead)
            logger.info(f"[UNIQUE LEAD] '{lead.business_name}' (ID: {lead.lead_id}) | Quality Score: {lead.quality_score}/100")

        processed_results.append({
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "city": lead.city,
            "quality_score": lead.quality_score,
            "status": lead.status,
            "is_duplicate": is_dup,
            "duplicate_reason": dup_reason
        })

    logger.info(f"Deduplication finished: {unique_count} unique leads, {duplicate_count} duplicates marked.")

    return {
        "processed_count": len(leads),
        "unique_count": unique_count,
        "duplicate_count": duplicate_count,
        "results": processed_results
    }
