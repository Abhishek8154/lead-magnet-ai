import re
import ssl
import time
import httpx
import requests
from typing import List, Dict, Any, Tuple, Optional
from config import config
from database import Database
from models import Lead, LeadStatus
from processing.normalize import normalize_business_name
from utils.logger import get_logger

logger = get_logger("WebsiteChecker")

# Social and Directory Domain Definitions
SOCIAL_DOMAINS = [
    "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com"
]

DIRECTORY_DOMAINS = [
    "justdial.com", "sulekha.com", "indiamart.com", "yellowpages.com",
    "zomato.com", "swiggy.com", "tripadvisor.com", "tripadvisor.in",
    "yelp.com", "magicpin.in", "dineout.co.in", "eattreat.in"
]


def classify_url_type(url: Optional[str]) -> Optional[str]:
    """
    Checks if a URL belongs to a social media platform or business directory.
    Returns 'SOCIAL_ONLY', 'DIRECTORY_ONLY', or None for standard website domains.
    """
    if not url:
        return None
    url_lower = url.lower().strip()
    for domain in SOCIAL_DOMAINS:
        if domain in url_lower:
            return "SOCIAL_ONLY"
    for domain in DIRECTORY_DOMAINS:
        if domain in url_lower:
            return "DIRECTORY_ONLY"
    return None


def search_official_website(business_name: str, city: Optional[str]) -> Tuple[Optional[str], str]:
    """
    Performs a secondary SerpAPI Google search for businesses missing a website URL:
    Query: "{business_name} {city} official website"
    Returns (candidate_url, status_classification).
    """
    if not config.SERPAPI_KEY or config.SERPAPI_KEY == "your-serpapi-key":
        return None, "NO_WEBSITE"

    city_str = city or ""
    query = f"{business_name} {city_str} official website".strip()
    logger.info(f"Performing secondary SerpAPI search: '{query}'")

    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "api_key": config.SERPAPI_KEY,
        "num": 5
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return None, "NO_WEBSITE"

        data = response.json()
        organic_results = data.get("organic_results", [])

        found_social = False
        found_directory = False

        for item in organic_results:
            link = item.get("link")
            if not link:
                continue

            url_type = classify_url_type(link)
            if url_type == "SOCIAL_ONLY":
                found_social = True
            elif url_type == "DIRECTORY_ONLY":
                found_directory = True
            else:
                # Found a non-social, non-directory candidate website URL
                logger.info(f"Found official website candidate via SerpAPI: '{link}' for '{business_name}'")
                return link, "VALID_WEBSITE"

        if found_social and not found_directory:
            return None, "SOCIAL_ONLY"
        elif found_directory:
            return None, "DIRECTORY_ONLY"

    except Exception as e:
        logger.warning(f"Secondary SerpAPI website search failed for '{business_name}': {e}")

    return None, "NO_WEBSITE"


def verify_website(url: str, business_name: str) -> str:
    """
    Makes an HTTP GET request using httpx with a 10-second timeout.
    Inspects HTTP status code, title, and page content to classify result:
    - VALID_WEBSITE
    - BROKEN_WEBSITE
    - DOMAIN_ONLY
    - SOCIAL_ONLY
    - DIRECTORY_ONLY
    - UNKNOWN
    """
    # 1. Initial Domain Type Check
    url_type = classify_url_type(url)
    if url_type:
        return url_type

    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = "http://" + target_url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        # Use httpx with 10-second timeout & SSL verification disable for broad compatibility
        with httpx.Client(timeout=10.0, follow_redirects=True, verify=False) as client:
            response = client.get(target_url, headers=headers)

            # Check redirected URL domain type
            redirect_type = classify_url_type(str(response.url))
            if redirect_type:
                return redirect_type

            if response.status_code >= 400:
                logger.warning(f"Website '{target_url}' returned HTTP status code {response.status_code}")
                return "BROKEN_WEBSITE"

            html = response.text.lower()

            # Parse Page Title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            page_title = title_match.group(1).strip() if title_match else ""

            # Check for Parked Domain / For Sale indicators
            parked_signals = [
                "domain for sale", "buy this domain", "parked domain",
                "domain name is reserved", "under construction", "site unavailable",
                "this domain is for sale"
            ]
            if any(signal in page_title or signal in html[:1500] for signal in parked_signals):
                logger.info(f"Website '{target_url}' classified as DOMAIN_ONLY (parked/under construction).")
                return "DOMAIN_ONLY"

            # Check Business Name Match in Page Title / Content
            norm_bname = normalize_business_name(business_name)
            tokens = [t for t in norm_bname.split() if len(t) > 2]

            matches_title = any(token in page_title for token in tokens)
            matches_content = sum(1 for token in tokens if token in html[:5000])

            if matches_title or matches_content >= max(1, len(tokens) // 2):
                logger.info(f"Website '{target_url}' verified successfully for '{business_name}'. Status: VALID_WEBSITE")
                return "VALID_WEBSITE"
            else:
                # Site loads fine (200 OK)
                logger.info(f"Website '{target_url}' loaded fine (200 OK). Status: VALID_WEBSITE")
                return "VALID_WEBSITE"

    except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout):
        logger.warning(f"Timeout verifying website '{target_url}'")
        return "BROKEN_WEBSITE"
    except (httpx.ConnectError, httpx.NetworkError):
        logger.warning(f"DNS/Connection error for website '{target_url}'")
        return "BROKEN_WEBSITE"
    except (httpx.HTTPStatusError, httpx.SSLError, ssl.SSLError):
        logger.warning(f"HTTP/SSL error for website '{target_url}'")
        return "BROKEN_WEBSITE"
    except Exception as e:
        logger.warning(f"Unexpected error verifying website '{target_url}': {e}")
        return "UNKNOWN"


def verify_leads_websites(
    batch_size: int = 5,
    db: Optional[Database] = None,
    delay_seconds: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Checks websites for leads with status DISCOVERED or ENRICHED in batches of size batch_size.
    Adds delay_seconds between requests to prevent 429 errors.
    Updates lead.website_status, lead.website_url (if found via search), and lead.status to VERIFIED.
    """
    if db is None:
        db = Database()
        db.init_db()

    all_leads = db.get_all_leads()
    # Filter target leads with status DISCOVERED or ENRICHED
    target_leads = [
        l for l in all_leads
        if l.status in (LeadStatus.DISCOVERED.value, LeadStatus.ENRICHED.value)
    ][:batch_size]

    if not target_leads:
        logger.info("No leads with status DISCOVERED or ENRICHED found for website verification.")
        return []

    logger.info(f"Starting website verification for {len(target_leads)} leads (batch_size={batch_size})...")
    results = []

    for idx, lead in enumerate(target_leads, 1):
        original_url = lead.website_url
        logger.info(f"[{idx}/{len(target_leads)}] Checking lead: '{lead.business_name}' | Original URL: '{original_url}'")

        # 1. Classify initial URL if present
        domain_type = classify_url_type(original_url)

        if domain_type:
            # If URL is a social link or directory link
            lead.website_status = domain_type
        elif original_url and original_url.lower() != "none":
            # Perform HTTP verification using httpx
            status_classification = verify_website(original_url, lead.business_name)
            lead.website_status = status_classification
        else:
            # Missing website URL - Perform secondary SerpAPI organic search
            found_url, search_status = search_official_website(lead.business_name, lead.city)
            if found_url:
                lead.website_url = found_url
                # Verify discovered URL
                lead.website_status = verify_website(found_url, lead.business_name)
            else:
                lead.website_status = search_status

        # Update Lead Status to VERIFIED
        lead.status = LeadStatus.VERIFIED.value
        db.upsert_lead(lead)

        logger.info(
            f"Result for '{lead.business_name}': Website URL: '{lead.website_url}', "
            f"website_status: '{lead.website_status}', status: '{lead.status}'"
        )

        results.append({
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "website_url": lead.website_url,
            "website_status": lead.website_status,
            "status": lead.status
        })

        # Add 1-second delay between checks
        if idx < len(target_leads):
            time.sleep(delay_seconds)

    logger.info("Website verification batch completed.")
    return results
