import json
from discovery.serpapi_search import discover_leads
from database import Database
from utils.logger import get_logger

logger = get_logger("TestDiscovery")

def run_test():
    city = "Vadodara"
    business_type = "restaurants"
    max_results = 5

    logger.info(f"Testing discovery with city='{city}', business_type='{business_type}', max_results={max_results}")

    db = Database()
    db.init_db()

    result = discover_leads(city=city, business_type=business_type, max_results=max_results, db=db)

    print("\n" + "="*80)
    print("RAW SERPAPI OUTPUT SUMMARY:")
    print("="*80)
    if result.get("error"):
        print(f"Error encountered: {result['error']}")
    else:
        raw_output = result.get("raw_output", {})
        search_metadata = raw_output.get("search_metadata", {})
        search_information = raw_output.get("search_information", {})
        local_results = raw_output.get("local_results", [])
        
        print(f"Search Status: {search_metadata.get('status')}")
        print(f"Google Maps URL: {search_metadata.get('google_maps_url')}")
        print(f"Total Results Count in Response: {len(local_results)}")
        print("\nRaw Local Results (First 5 items):")
        print(json.dumps(local_results[:5], indent=2))

    print("\n" + "="*80)
    print("SAVED LEADS IN SQLITE DATABASE:")
    print("="*80)
    all_leads = db.get_all_leads()
    for idx, lead in enumerate(all_leads, 1):
        print(f"\n[{idx}] Lead ID: {lead.lead_id}")
        print(f"    Business Name  : {lead.business_name}")
        print(f"    Category       : {lead.category}")
        print(f"    City           : {lead.city}")
        print(f"    Phone          : {lead.phone}")
        print(f"    Address        : {lead.address}")
        print(f"    Website        : {lead.website_url}")
        print(f"    Status         : {lead.status}")
        print(f"    Source URL     : {lead.source_url}")

if __name__ == "__main__":
    run_test()
