"""
One-time script: Reset FAILED WhatsApp leads and attempt email fallback
for all leads that have a valid email address.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from outreach.email_sender import send_approved_emails

db = Database()
db.init_db()

all_leads = db.get_all_leads()

# Find leads where WhatsApp failed AND email not yet sent AND email exists
fallback_targets = [
    l for l in all_leads
    if l.whatsapp_status == "FAILED"
    and l.email and str(l.email).strip()
    and l.email_status not in ("SENT", "DRY_RUN_SENT")
    and l.approval_status == "APPROVED"
]

print(f"Found {len(fallback_targets)} leads eligible for email fallback:")
for l in fallback_targets:
    print(f"  - {l.business_name} | email: {l.email}")

if fallback_targets:
    print(f"\nSending emails to {len(fallback_targets)} leads...")
    results = send_approved_emails(leads=fallback_targets, db=db)
    sent = [r for r in results if r.get("email_status") == "SENT"]
    failed = [r for r in results if r.get("email_status") != "SENT"]
    print(f"\n✅ Email sent: {len(sent)}")
    print(f"❌ Email failed: {len(failed)}")
    for r in sent:
        print(f"  ✓ {r.get('business_name')} → {r.get('email')}")
else:
    print("No leads eligible for email fallback (either no email, or already sent).")

# Summary
all_leads2 = db.get_all_leads()
wa_sent = [l for l in all_leads2 if l.whatsapp_status == "SENT"]
email_sent = [l for l in all_leads2 if l.email_status == "SENT"]
wa_failed = [l for l in all_leads2 if l.whatsapp_status == "FAILED"]
print(f"\n--- Final Status ---")
print(f"WhatsApp SENT:  {len(wa_sent)}")
print(f"Email SENT:     {len(email_sent)}")
print(f"WhatsApp FAILED (no email available): {len(wa_failed)}")
