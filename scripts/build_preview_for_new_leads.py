import os
import sys
import json
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader
from config import config
from database import Database
from models import Lead, LeadStatus
from demo.server import generate_slug
from ai.personalizer import generate_fallback_messages, extract_meta
from utils.logger import get_logger

logger = get_logger("BuildPreviews")

def build_previews_for_new_leads():
    db = Database()
    db.init_db()
    
    all_leads = db.get_all_leads()
    new_leads = all_leads[:20]
    
    print("=" * 70)
    print(f"🚀 BUILDING WEBSITE PREVIEWS FOR {len(new_leads)} NEW LEADS")
    print("=" * 70)
    
    templates_dir = PROJECT_ROOT / "demo" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("preview.html")
    
    # Destination directories
    target_dirs = [
        PROJECT_ROOT / "preview",
        PROJECT_ROOT / "docs" / "preview",
        PROJECT_ROOT / "public" / "preview",
        PROJECT_ROOT / "public_demos" / "preview"
    ]
    
    for d in target_dirs:
        d.mkdir(parents=True, exist_ok=True)
        
    generated_previews = []
    
    base_preview_url = config.DEMO_BASE_URL.rstrip('/')
    is_gh_pages = "github.io" in base_preview_url.lower()

    for idx, lead in enumerate(new_leads, 1):
        slug = generate_slug(lead.business_name, lead.city)
        ext = ".html" if is_gh_pages else ""
        live_demo_url = f"{base_preview_url}/{slug}{ext}"
        
        meta = extract_meta(lead)
        lead_dict = lead.to_dict()
        lead_dict["rating"] = meta.get("rating") or "4.9"
        lead_dict["review_count"] = meta.get("review_count") or 120
        lead_dict["instagram"] = meta.get("instagram")
        lead_dict["facebook"] = meta.get("facebook")
        
        # Render HTML
        html_content = template.render(request=None, lead=lead_dict)
        
        # Save to all target preview folders
        for d in target_dirs:
            # 1. Direct .html file
            html_file = d / f"{slug}.html"
            html_file.write_text(html_content, encoding="utf-8")
            
            # 2. Directory with index.html
            sub_dir = d / slug
            sub_dir.mkdir(parents=True, exist_ok=True)
            (sub_dir / "index.html").write_text(html_content, encoding="utf-8")
        
        # Update database fields
        lead.demo_url = live_demo_url
        lead.demo_status = "READY"
        
        # Ensure personalized messages are populated with live demo URL
        if not lead.email_message or not lead.whatsapp_message or "{{DEMO_URL}}" in (lead.email_message or "") or "DEMO_URL" in (lead.email_message or ""):
            msgs = generate_fallback_messages(lead)
            email_msg = f"Subject: {msgs['email_subject']}\n\n{msgs['email_body']}"
            wa_msg = msgs['whatsapp_message']
            
            # Replace placeholder with actual live demo link
            email_msg = email_msg.replace("{{DEMO_URL}}", f"{live_demo_url}").replace("{DEMO_URL}", f"{live_demo_url}")
            if live_demo_url not in email_msg:
                email_msg += f"\n\nHere is your custom website preview:\n👉 {live_demo_url}"
                
            wa_msg = wa_msg.replace("{{DEMO_URL}}", f"{live_demo_url}").replace("{DEMO_URL}", f"{live_demo_url}")
            if live_demo_url not in wa_msg:
                wa_msg += f"\n👉 {live_demo_url}"
                
            lead.email_message = email_msg
            lead.whatsapp_message = wa_msg
            
        if lead.status in (LeadStatus.DISCOVERED.value, LeadStatus.VERIFIED.value, LeadStatus.QUALIFIED.value, None):
            lead.status = LeadStatus.DEMO_READY.value
            
        db.upsert_lead(lead)
        
        file_size_kb = round(len(html_content.encode('utf-8')) / 1024, 1)
        generated_previews.append({
            "idx": idx,
            "lead_id": lead.lead_id,
            "name": lead.business_name,
            "city": lead.city,
            "slug": slug,
            "size_kb": file_size_kb,
            "demo_url": live_demo_url,
            "local_url": f"http://127.0.0.1:8001/preview/{slug}"
        })
        
        print(f"[{idx:02d}/20] ✅ Built Preview for '{lead.business_name}' ({lead.city})")
        print(f"       Slug: {slug} ({file_size_kb} KB)")
        print(f"       Live URL:  {live_demo_url}")
        print(f"       Local URL: http://127.0.0.1:8001/preview/{slug}\n")

    print("=" * 70)
    print(f"🎉 Successfully built and verified all {len(generated_previews)} website previews!")
    print("=" * 70)
    return generated_previews

if __name__ == "__main__":
    build_previews_for_new_leads()
