import os
import sys
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from database import Database
from models import Lead
from demo.server import generate_slug
from ai.personalizer import generate_fallback_messages
from utils.logger import get_logger

logger = get_logger("ApplyProfessionalMessages")

def apply_professional_messages():
    db = Database()
    db.init_db()
    
    leads = db.get_all_leads()
    print("=" * 70)
    print(f"🔄 APPLYING PROFESSIONAL OUTREACH MESSAGES TO {len(leads)} LEADS")
    print("=" * 70)
    
    base_preview_url = config.DEMO_BASE_URL.rstrip('/')
    is_gh_pages = "github.io" in base_preview_url.lower()

    updated = 0
    for idx, lead in enumerate(leads, 1):
        slug = generate_slug(lead.business_name, lead.city)
        ext = ".html" if is_gh_pages else ""
        live_demo_url = lead.demo_url or f"{base_preview_url}/{slug}{ext}"
        
        # Generate new professional executive message
        msg_dict = generate_fallback_messages(lead)
        
        email_msg = f"Subject: {msg_dict['email_subject']}\n\n{msg_dict['email_body']}"
        wa_msg = msg_dict['whatsapp_message']
        
        # Inject live demo URL
        email_msg = email_msg.replace("{{DEMO_URL}}", live_demo_url).replace("{DEMO_URL}", live_demo_url)
        if live_demo_url not in email_msg:
            email_msg += f"\n\nHere is your custom website preview:\n👉 {live_demo_url}"
            
        wa_msg = wa_msg.replace("{{DEMO_URL}}", live_demo_url).replace("{DEMO_URL}", live_demo_url)
        if live_demo_url not in wa_msg:
            wa_msg += f"\n👉 {live_demo_url}"
            
        lead.email_message = email_msg
        lead.whatsapp_message = wa_msg
        lead.demo_url = live_demo_url
        
        db.upsert_lead(lead)
        updated += 1
        
        if idx <= 5:
            print(f"\n--- [SAMPLE {idx}: {lead.business_name} ({lead.city})] ---")
            print(f"[EMAIL PREVIEW]\n{email_msg}\n")
            print(f"[WHATSAPP PREVIEW]\n{wa_msg}\n")

    print("=" * 70)
    print(f"✅ Successfully updated {updated} leads with professional outreach copy!")
    print("=" * 70)

if __name__ == "__main__":
    apply_professional_messages()
