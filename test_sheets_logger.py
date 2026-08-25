import json
from database import Database
from sheets_logging.sheets_logger import GoogleSheetsLogger, LEADS_HEADERS, RUNS_HEADERS
from utils.logger import get_logger

logger = get_logger("TestSheetsLogger")

def run_test():
    db = Database()
    db.init_db()

    # 1. Fetch 5 Vadodara restaurant leads from SQLite
    all_leads = db.get_all_leads()
    vadodara_leads = [l for l in all_leads if l.city == "Vadodara"]

    logger.info(f"Loaded {len(vadodara_leads)} Vadodara restaurant leads for Google Sheets sync test.")

    # 2. Instantiate GoogleSheetsLogger
    sheets_logger = GoogleSheetsLogger()

    # 3. Attempt Google Sheets Sync
    synced_count = 0
    fail_count = 0

    for lead in vadodara_leads:
        success = sheets_logger.sync_lead(lead)
        if success:
            synced_count += 1
        else:
            fail_count += 1

    # Calculate stats for run summary
    stats = {
        "discovered": len([l for l in vadodara_leads if l.status == "DISCOVERED"]),
        "qualified": len([l for l in vadodara_leads if l.status in ("QUALIFIED", "PERSONALIZED", "DEMO_READY")]),
        "hot": len([l for l in vadodara_leads if l.lead_tier == "HOT"]),
        "warm": len([l for l in vadodara_leads if l.lead_tier == "WARM"]),
        "demo_ready": len([l for l in vadodara_leads if l.status == "DEMO_READY"]),
        "errors": fail_count
    }

    sheets_logger.log_run_summary(city="Vadodara", business_type="restaurants", stats=stats)

    print("\n" + "="*95)
    print("GOOGLE SHEETS SYNC OUTPUT SUMMARY")
    print("="*95)
    print(f"Sheet ID Target    : {sheets_logger.sheet_id}")
    print(f"Credentials Path   : {sheets_logger.creds_path}")
    print(f"Leads Attempted    : {len(vadodara_leads)}")
    print(f"Successfully Synced: {synced_count}")
    print(f"Local Queue / Auth : {fail_count} (Saved to logs/sheets_sync_queue.json)")

    print("\n" + "="*95)
    print("LEADS TAB COLUMN HEADERS (26 Columns):")
    print("="*95)
    print(" | ".join(LEADS_HEADERS))

    print("\n" + "="*95)
    print("SAMPLE SYNCED ROW DATA (First 3 Leads):")
    print("="*95)
    for idx, lead in enumerate(vadodara_leads[:3], 1):
        row = sheets_logger.lead_to_row(lead)
        print(f"\n[Lead {idx}: {lead.business_name}]")
        print(f"  Row Data (26 columns):")
        print(f"    1-5  : {row[0:5]}")
        print(f"    6-10 : {row[5:10]}")
        print(f"    11-15: {row[10:15]}")
        print(f"    16-20: {row[15:20]}")
        print(f"    21-26: {row[20:26]}")

    print("\n" + "="*95)
    print("RUNS TAB SUMMARY ROW FORMAT (9 Columns):")
    print("="*95)
    print("Headers : " + " | ".join(RUNS_HEADERS))
    print(f"Data    : Vadodara | restaurants | Discovered={stats['discovered']} | Qualified={stats['qualified']} | HOT={stats['hot']} | WARM={stats['warm']} | DemoReady={stats['demo_ready']} | Errors={stats['errors']}")

if __name__ == "__main__":
    run_test()
