import csv
from database import Database
from sheets_logging.sheets_logger import LEADS_HEADERS

db = Database()
db.init_db()
leads = db.get_all_leads()

with open("leads_export.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(LEADS_HEADERS)
    for lead in leads:
        writer.writerow([
            lead.lead_id,
            lead.business_name,
            lead.category or "",
            lead.city or "",
            lead.phone or "",
            lead.email or "",
            lead.address or "",
            lead.website_url or "",
            lead.website_status or "",
            lead.lead_score or 0,
            lead.lead_tier or "",
            lead.qualification_reason or "",
            lead.demo_url or "",
            lead.demo_status or "",
            lead.email_message or "",
            lead.whatsapp_message or "",
            lead.approval_status or "PENDING",
            lead.email_status or "NOT_SENT",
            lead.whatsapp_status or "NOT_SENT",
            getattr(lead, "first_contacted_at", "") or "",
            getattr(lead, "last_contacted_at", "") or "",
            lead.status or "",
            lead.source_url or "",
            lead.created_at or "",
            lead.updated_at or "",
            lead.error_log or ""
        ])

print(f"Exported {len(leads)} leads to leads_export.csv successfully.")
