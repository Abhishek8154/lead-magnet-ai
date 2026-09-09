import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import Database
from config import config
from demo.server import generate_slug
from ai.personalizer import generate_fallback_messages
from demo.export_static_demos import export_all_static_demos
from sheets_logging.sheets_logger import GoogleSheetsLogger
import subprocess

db = Database()
db.init_db()
leads = db.get_all_leads()
print(f"Updating copy and live demo URLs for {len(leads)} leads...")

base_url = "https://abhishek8154.github.io/lead-magnet-ai/preview"

for lead in leads:
    slug = generate_slug(lead.business_name, lead.city)
    demo_url = f"{base_url}/{slug}.html"
    lead.demo_url = demo_url
    lead.demo_status = "READY"
    
    msgs = generate_fallback_messages(lead)
    
    # Format email & whatsapp
    lead.email_message = f"Subject: {msgs['email_subject']}\n\n{msgs['email_body']}".replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
    lead.whatsapp_message = msgs["whatsapp_message"].replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
    
    db.upsert_lead(lead)

print("Successfully updated all leads in SQLite database.")

# Export static files to docs and public_demos
export_all_static_demos()

# Push to GitHub
try:
    subprocess.run(["git", "add", "docs", "public_demos", "public"], cwd=str(PROJECT_ROOT), check=True)
    subprocess.run(["git", "commit", "-m", "Update demo URLs and high-converting copy"], cwd=str(PROJECT_ROOT), capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, timeout=60)
    print("Pushed latest demos to GitHub Pages!")
except Exception as e:
    print("Git sync note:", e)

# Sync to Google Sheets
sheets = GoogleSheetsLogger()
s_cnt, f_cnt = sheets.sync_all_leads(db=db)
print(f"Google Sheets sync: {s_cnt} synced, {f_cnt} failed.")
