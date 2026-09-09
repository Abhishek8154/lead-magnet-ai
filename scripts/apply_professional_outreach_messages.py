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

logger = get_logger("ApplyCloudflareMessages")

def apply_cloudflare_messages():
    db = Database()
    db.init_db()
    
    leads = db.get_all_leads()
    print("=" * 70)
    print(f"🔄 APPLYING WORKING CLOUDFLARE DEMO URLS TO {len(leads)} LEADS")
    print("=" * 70)
    
    base_preview_url = "https://ice-delivered-icq-scott.trycloudflare.com/preview"

    updated = 0
    for idx, lead in enumerate(leads, 1):
        slug = generate_slug(lead.business_name, lead.city)
        live_demo_url = f"{base_preview_url}/{slug}"
        
        # Professional message
        wa_msg = (
            f"Dear {lead.business_name} Team,\n\n"
            f"I hope you're having a productive week.\n\n"
            f"I noticed {lead.business_name}'s strong reputation in {lead.city} and put together a modern, interactive website concept to help showcase your clinical work and treatments to prospective patients:\n\n"
            f"👉 {live_demo_url}\n\n"
            f"Whenever you have a quick moment, take a look and let me know if this is something you'd like to explore for your practice.\n\n"
            f"Best regards,\nAbhishek"
        )
        
        email_msg = f"Subject: Tailored Website Concept for {lead.business_name}\n\n{wa_msg}"
        
        lead.email_message = email_msg
        lead.whatsapp_message = wa_msg
        lead.demo_url = live_demo_url
        
        db.upsert_lead(lead)
        updated += 1
        
        if idx <= 3:
            print(f"\n--- [SAMPLE {idx}: {lead.business_name} ({lead.city})] ---")
            print(f"👉 LIVE DEMO URL: {live_demo_url}")
            print(f"[WHATSAPP PREVIEW]\n{wa_msg}\n")

    print("=" * 70)
    print(f"✅ Successfully updated {updated} leads with working Cloudflare links!")
    print("=" * 70)

if __name__ == "__main__":
    apply_cloudflare_messages()
