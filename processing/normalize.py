import re
import json
from urllib.parse import urlparse
from typing import Optional
from models import Lead


def normalize_business_name(name: Optional[str]) -> str:
    """
    Normalizes business name:
    - Lowercase
    - Remove corporate suffixes (ltd, pvt, pvt.ltd, private limited, limited, Inc, Corp, &)
    - Remove punctuation and strip whitespace
    """
    if not name:
        return ""

    text = name.lower().strip()

    # Common corporate suffixes and connector symbols to strip out
    patterns = [
        r"\bpvt\.?\s*ltd\.?\b",
        r"\bprivate\s+limited\b",
        r"\blimited\b",
        r"\bltd\.?\b",
        r"\binc\.?\b",
        r"\bcorp\.?\b",
        r"\bco\.?\b",
        r"&",
        r"\band\b"
    ]

    for pat in patterns:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)

    # Remove extra special characters and non-alphanumeric chars except space
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_phone(phone: Optional[str]) -> str:
    """
    Normalizes phone numbers:
    - Strip spaces, dashes, dots, parentheses, +
    - Remove +91 or 91 country code for Indian numbers if length is 12 digits
    - Keep 10 digits
    """
    if not phone:
        return ""

    # Keep only digits
    digits = re.sub(r"\D", "", phone)

    # Handle Indian 12-digit numbers starting with 91 (e.g. 919876543210 -> 9876543210)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    return digits


def normalize_website(url: Optional[str]) -> str:
    """
    Normalizes website URLs:
    - Lowercase
    - Strip scheme (http://, https://)
    - Remove www.
    - Remove trailing slash /
    """
    if not url:
        return ""

    clean_url = url.lower().strip()

    # Add scheme if missing for urlparse
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "http://" + clean_url

    parsed = urlparse(clean_url)
    domain = parsed.netloc or parsed.path

    # Remove www.
    if domain.startswith("www."):
        domain = domain[4:]

    # Remove port if default
    domain = domain.split(":")[0]

    # Combine domain and path (stripped of trailing slash)
    path = parsed.path.rstrip("/") if parsed.netloc else ""
    
    normalized = f"{domain}{path}".strip("/")
    return normalized


def normalize_address(address: Optional[str]) -> str:
    """
    Normalizes address:
    - Lowercase
    - Strip extra spaces and newlines
    """
    if not address:
        return ""

    text = address.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def calculate_quality_score(lead: Lead) -> int:
    """
    Calculates a Quality Score (0 - 100) for a lead based on available details:
    - Has phone number: +20
    - Has website URL: +20
    - Has address: +20
    - Has rating: +10
    - Has email: +15
    - Has 10+ reviews: +15
    """
    score = 0

    # 1. Phone (+20)
    if lead.phone and len(normalize_phone(lead.phone)) >= 7:
        score += 20

    # 2. Website (+20)
    if lead.website_url and len(normalize_website(lead.website_url)) > 0:
        score += 20

    # 3. Address (+20)
    if lead.address and len(normalize_address(lead.address)) > 5:
        score += 20

    # 4. Email (+15)
    if lead.email and "@" in lead.email:
        score += 15

    # Inspect raw_data for rating and review_count
    rating = None
    review_count = 0

    if lead.raw_data:
        try:
            raw_meta = json.loads(lead.raw_data)
            rating = raw_meta.get("rating")
            review_count = raw_meta.get("review_count") or 0
        except (json.JSONDecodeError, TypeError):
            pass

    # 5. Has rating (+10)
    if rating is not None and float(rating) > 0:
        score += 10

    # 6. Has 10+ reviews (+15)
    if review_count and int(review_count) >= 10:
        score += 15

    return min(score, 100)
