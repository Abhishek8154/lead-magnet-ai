import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import Database
from ai.personalizer import generate_fallback_messages, clean_business_name

db = Database()
db.init_db()

leads = db.get_all_leads()
print(f"Updating {len(leads)} leads in database with new copy...")

for lead in leads:
    msgs = generate_fallback_messages(lead)
    
    demo_url = lead.demo_url
    if not demo_url:
        from demo.server import generate_slug
        slug = generate_slug(lead.business_name, lead.city)
        demo_url = f"https://abhishek8154.github.io/lead-magnet-ai/preview/{slug}.html"

    em = msgs['email_body'].replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
    lead.email_message = f"Subject: {msgs['email_subject']}\n\n{em}"
    
    wa = msgs['whatsapp_message'].replace("{{DEMO_URL}}", demo_url).replace("{DEMO_URL}", demo_url)
    lead.whatsapp_message = wa
    
    db.upsert_lead(lead)
    print(f"Updated: {clean_business_name(lead.business_name)} ({lead.website_status})")
    print(f"  WA Preview: {wa[:90]}...\n")

print("All leads updated successfully.")
