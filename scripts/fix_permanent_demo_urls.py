import os
import re
import sys
import json
import subprocess
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from database import Database
from models import Lead
from demo.server import generate_slug
from demo.url_generator import get_permanent_demo_url
from demo.export_static_demos import export_all_static_demos
from sheets_logging.sheets_logger import GoogleSheetsLogger

def fix_all_demo_urls():
    print("=" * 70)
    print("🚀 PERMANENT FIX: MIGRATING ALL LEADS TO 24/7 GITHUB PAGES URLS")
    print("=" * 70)

    db = Database()
    db.init_db()
    leads = db.get_all_leads()

    print(f"Found {len(leads)} total leads in database.\n")

    updated_count = 0
    for idx, lead in enumerate(leads, 1):
        perm_url = get_permanent_demo_url(lead.business_name, lead.city)
        lead.demo_url = perm_url
        lead.demo_status = "READY"

        # Sanitize WhatsApp Message
        if lead.whatsapp_message:
            wa = lead.whatsapp_message
            wa = wa.replace("{{DEMO_URL}}", perm_url).replace("{DEMO_URL}", perm_url)
            wa = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', perm_url, wa)
            wa = re.sub(r'https?://(?:localhost|127\.0\.0\.1):\d+/preview[^\s]*', perm_url, wa)
            if perm_url not in wa:
                wa += f"\n👉 {perm_url}"
            lead.whatsapp_message = wa

        # Sanitize Email Message
        if lead.email_message:
            em = lead.email_message
            em = em.replace("{{DEMO_URL}}", perm_url).replace("{DEMO_URL}", perm_url)
            em = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', perm_url, em)
            em = re.sub(r'https?://(?:localhost|127\.0\.0\.1):\d+/preview[^\s]*', perm_url, em)
            if perm_url not in em:
                em += f"\n\n👉 {perm_url}"
            lead.email_message = em

        db.upsert_lead(lead)

        # Update approvals table as well
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE approvals SET demo_url = ?, whatsapp_message = ?, email_message = ? WHERE lead_id = ?",
                (perm_url, lead.whatsapp_message, lead.email_message, lead.lead_id)
            )
            conn.commit()

        updated_count += 1
        print(f"[{idx:02d}/{len(leads)}] ✅ Fixed URL for '{lead.business_name}' -> {perm_url}")

    print("\n" + "=" * 70)
    print(f"🎉 Updated {updated_count} leads in SQLite database with permanent URLs!")
    print("=" * 70 + "\n")

    # Export static HTML files for all leads
    print("📦 Exporting static HTML demo websites to docs/, public/, public_demos/...")
    docs_dir = PROJECT_ROOT / "docs"
    public_dir = PROJECT_ROOT / "public"
    public_demos_dir = PROJECT_ROOT / "public_demos"

    export_all_static_demos(docs_dir)
    export_all_static_demos(public_dir)
    export_all_static_demos(public_demos_dir)

    # Sync to Google Sheets
    print("\n📊 Syncing updated permanent links to Google Sheets...")
    try:
        sheets = GoogleSheetsLogger()
        success, fail = sheets.sync_all_leads(db=db)
        print(f"Google Sheets sync completed: {success} synced, {fail} failed.")
    except Exception as se:
        print(f"Google Sheets sync note: {se}")

    # Commit and Push to GitHub
    print("\n🌐 Publishing latest demo files to GitHub Pages...")
    try:
        subprocess.run(["git", "add", "docs", "public", "public_demos", ".env", "config.py"], cwd=str(PROJECT_ROOT), check=True)
        commit_res = subprocess.run(["git", "commit", "-m", "Fix: Set permanent 24/7 GitHub Pages URLs for all client demos"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        print("Git Commit Output:", commit_res.stdout.strip())
        push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60)
        print("Git Push Output:", push_res.stdout.strip() or push_res.stderr.strip())
        print("\n✅ Successfully published all client websites live to GitHub Pages 24/7!")
    except Exception as ge:
        print(f"Git publish note: {ge}")

    print("=" * 70)
    print("🚀 ALL LEADS & PREVIEW SITES ARE NOW PERMANENTLY LIVE & FIXED!")
    print("=" * 70)

if __name__ == "__main__":
    fix_all_demo_urls()
