import sys
import os
import threading
import time
from pathlib import Path

# Add project root directory to sys.path so direct invocation works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Optional
import uvicorn
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from config import config
from database import Database
from models import Lead, LeadStatus
from approval.approval_viewer import process_lead_decision
from followup.followup_engine import FollowupEngine
from demo.server import preview_lead_page, preview_fallback_page

app = FastAPI(title="Lead Magnet AI - Command Dashboard")

# Mount demo preview routes on main web app
app.add_api_route("/preview/{slug:path}", preview_lead_page, methods=["GET"], response_class=HTMLResponse)
app.add_api_route("/preview", preview_fallback_page, methods=["GET"], response_class=HTMLResponse)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
db = Database()
db.init_db()


@app.get("/", response_class=HTMLResponse)
def read_dashboard(request: Request):
    """Renders the main command dashboard HTML page."""
    all_leads = db.get_all_leads()

    delivered_cnt = len([l for l in all_leads if l.email_status == "SENT" or l.whatsapp_status in ("SENT", "WA_DIRECT_READY")])
    failed_cnt = len([l for l in all_leads if l.email_status == "FAILED" or l.whatsapp_status == "FAILED"])
    dry_run_cnt = len([l for l in all_leads if l.email_status == "DRY_RUN_SENT" or l.whatsapp_status == "DRY_RUN_SENT"])

    stats = {
        "total_leads": len(all_leads),
        "hot_leads": len([l for l in all_leads if l.lead_tier == "HOT"]),
        "warm_leads": len([l for l in all_leads if l.lead_tier == "WARM"]),
        "demo_ready": len([l for l in all_leads if l.demo_status == "READY"]),
        "pending_approval": len([l for l in all_leads if l.approval_status in ("PENDING_APPROVAL", "PENDING")]),
        "outreach_sent": delivered_cnt + dry_run_cnt,
        "outreach_delivered": delivered_cnt,
        "outreach_failed": failed_cnt,
        "outreach_dry_run": dry_run_cnt
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "leads": [l.to_dict() for l in all_leads],
        "stats": stats,
        "config": config
    })


@app.get("/api/stats")
def get_stats():
    """Returns JSON analytics for the dashboard."""
    all_leads = db.get_all_leads()
    delivered_cnt = len([l for l in all_leads if l.email_status == "SENT" or l.whatsapp_status in ("SENT", "WA_DIRECT_READY")])
    failed_cnt = len([l for l in all_leads if l.email_status == "FAILED" or l.whatsapp_status == "FAILED"])
    dry_run_cnt = len([l for l in all_leads if l.email_status == "DRY_RUN_SENT" or l.whatsapp_status == "DRY_RUN_SENT"])

    return {
        "total_leads": len(all_leads),
        "hot_leads": len([l for l in all_leads if l.lead_tier == "HOT"]),
        "warm_leads": len([l for l in all_leads if l.lead_tier == "WARM"]),
        "low_leads": len([l for l in all_leads if l.lead_tier == "LOW"]),
        "demo_ready": len([l for l in all_leads if l.demo_status == "READY"]),
        "pending_approval": len([l for l in all_leads if l.approval_status in ("PENDING_APPROVAL", "PENDING")]),
        "outreach_sent": delivered_cnt + dry_run_cnt,
        "outreach_delivered": delivered_cnt,
        "outreach_failed": failed_cnt,
        "outreach_dry_run": dry_run_cnt,
        "dry_run_mode": config.DRY_RUN
    }


@app.api_route("/api/set-mode/{mode_name}", methods=["GET", "POST"])
@app.api_route("/api/set-mode", methods=["GET", "POST"])
@app.api_route("/api/toggle-dry-run", methods=["GET", "POST"])
def set_system_mode(mode_name: Optional[str] = None, mode: Optional[str] = None):
    """Explicitly sets or toggles DRY_RUN mode dynamically and updates .env file."""
    target = mode_name or mode
    if target:
        mode_clean = str(target).strip().lower()
        if mode_clean in ("dry", "dry_run", "true", "1"):
            config.DRY_RUN = True
        elif mode_clean in ("live", "false", "real", "0"):
            config.DRY_RUN = False
        else:
            config.DRY_RUN = not config.DRY_RUN
    else:
        config.DRY_RUN = not config.DRY_RUN

    # Persist change to .env file
    try:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            if re.search(r"DRY_RUN\s*=", content, re.IGNORECASE):
                new_content = re.sub(r"(?i)DRY_RUN\s*=\s*\w+", f"DRY_RUN={'true' if config.DRY_RUN else 'false'}", content)
            else:
                new_content = content.rstrip() + f"\nDRY_RUN={'true' if config.DRY_RUN else 'false'}\n"
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(new_content)
    except Exception as e:
        print(f"Error persisting DRY_RUN to .env: {e}")

    return {
        "status": "success",
        "dry_run": config.DRY_RUN,
        "mode": "DRY_RUN" if config.DRY_RUN else "LIVE",
        "message": f"Switched system mode to {'DRY RUN' if config.DRY_RUN else 'LIVE DISPATCH'}."
    }


@app.get("/api/leads")
def get_leads():
    """Returns all leads as JSON array."""
    all_leads = db.get_all_leads()
    return [l.to_dict() for l in all_leads]


@app.get("/api/outreach-tracker")
def get_outreach_tracker():
    """Returns detailed outreach delivery status for every lead that has been through outreach."""
    all_leads = db.get_all_leads()

    email_delivered = []
    email_failed = []
    email_dry_run = []
    whatsapp_delivered = []
    whatsapp_failed = []
    whatsapp_dry_run = []
    not_sent = []

    for lead in all_leads:
        lead_info = {
            "lead_id": lead.lead_id,
            "business_name": lead.business_name,
            "city": lead.city or "N/A",
            "category": lead.category or "N/A",
            "phone": lead.phone or "",
            "email": lead.email or "",
            "lead_tier": lead.lead_tier or "LOW",
            "lead_score": lead.lead_score,
            "email_status": lead.email_status or "NOT_SENT",
            "whatsapp_status": lead.whatsapp_status or "NOT_SENT",
            "approval_status": lead.approval_status or "PENDING",
            "demo_url": lead.demo_url or "",
            "last_contacted_at": lead.last_contacted_at or "",
            "error_log": lead.error_log or "",
            "status": lead.status or "",
        }

        # Classify email delivery
        if lead.email_status == "SENT":
            email_delivered.append(lead_info)
        elif lead.email_status == "FAILED":
            email_failed.append(lead_info)
        elif lead.email_status == "DRY_RUN_SENT":
            email_dry_run.append(lead_info)

        # Classify WhatsApp delivery
        if lead.whatsapp_status in ("SENT", "WA_DIRECT_READY"):
            whatsapp_delivered.append(lead_info)
        elif lead.whatsapp_status == "FAILED":
            whatsapp_failed.append(lead_info)
        elif lead.whatsapp_status == "DRY_RUN_SENT":
            whatsapp_dry_run.append(lead_info)

        # Leads approved but not yet sent
        if (lead.approval_status == "APPROVED" and
            lead.email_status == "NOT_SENT" and
            lead.whatsapp_status == "NOT_SENT"):
            not_sent.append(lead_info)

    return {
        "email_delivered": email_delivered,
        "email_failed": email_failed,
        "email_dry_run": email_dry_run,
        "whatsapp_delivered": whatsapp_delivered,
        "whatsapp_failed": whatsapp_failed,
        "whatsapp_dry_run": whatsapp_dry_run,
        "not_sent": not_sent,
        "summary": {
            "total_email_delivered": len(email_delivered),
            "total_email_failed": len(email_failed),
            "total_email_dry_run": len(email_dry_run),
            "total_whatsapp_delivered": len(whatsapp_delivered),
            "total_whatsapp_failed": len(whatsapp_failed),
            "total_whatsapp_dry_run": len(whatsapp_dry_run),
            "total_not_sent": len(not_sent),
        }
    }


@app.post("/api/approve/{lead_id}")
def approve_lead(lead_id: str):
    """Approves a lead for outreach and automatically dispatches Email + WhatsApp messages."""
    success, msg = process_lead_decision(lead_id=lead_id, action="A", db=db)
    if success:
        lead = db.get_lead_by_id(lead_id)
        wa_url = ""
        if lead:
            from outreach.email_sender import send_approved_emails
            from outreach.whatsapp_sender import send_approved_whatsapp_messages, format_whatsapp_phone
            import urllib.parse
            
            e_res = send_approved_emails(leads=[lead], db=db)
            w_res = send_approved_whatsapp_messages(leads=[lead], db=db)
            msg += f" Dispatched outreach ({len(e_res)} email, {len(w_res)} WhatsApp)."
            
            phone = format_whatsapp_phone(lead.phone)
            if phone:
                demo_link = lead.demo_url or ""
                if "trycloudflare.com" in demo_link or not demo_link:
                    from demo.server import generate_slug
                    slug = generate_slug(lead.business_name, lead.city)
                    target_base = config.DEMO_BASE_URL.rstrip("/")
                    demo_link = f"{target_base}/{slug}"
                    lead.demo_url = demo_link
                    db.upsert_lead(lead)

                text = lead.whatsapp_message or f"Hi {lead.business_name}, check your personalized website demo here: {demo_link}"
                # Replace placeholders
                text = text.replace("{{DEMO_URL}}", demo_link).replace("{DEMO_URL}", demo_link)
                # Replace legacy trycloudflare links if any remain
                import re
                text = re.sub(r'https?://[a-zA-Z0-9-]+\.trycloudflare\.com/preview[^\s]*', demo_link, text)
                if demo_link and demo_link not in text:
                    text += f"\n👉 {demo_link}"
                wa_url = f"https://api.whatsapp.com/send?phone={phone}&text={urllib.parse.quote(text)}"

        return {"status": "success", "message": msg, "whatsapp_url": wa_url}
    return JSONResponse(status_code=400, content={"status": "error", "message": msg})



@app.post("/api/approve-all")
def approve_all_leads():
    """Approves all pending leads and dispatches outreach automatically."""
    all_leads = db.get_all_leads()
    pending = [l for l in all_leads if l.approval_status in ("PENDING_APPROVAL", "PENDING")]
    approved_count = 0

    for lead in pending:
        lead.approval_status = "APPROVED"
        lead.status = LeadStatus.APPROVED.value
        db.upsert_lead(lead)
        approved_count += 1

    from outreach.email_sender import send_approved_emails
    from outreach.whatsapp_sender import send_approved_whatsapp_messages
    e_res = send_approved_emails(db=db)
    w_res = send_approved_whatsapp_messages(db=db)

    msg = f"Auto-approved and dispatched outreach for {approved_count} leads ({len(e_res)} emails, {len(w_res)} WhatsApp messages)."
    return {"status": "success", "approved_count": approved_count, "message": msg}


@app.post("/api/toggle-autopilot")
def toggle_autopilot(enabled: bool = True):
    """Toggles Auto-Pilot auto-approval mode."""
    config.AUTO_APPROVE = enabled
    return {"status": "success", "auto_pilot": config.AUTO_APPROVE, "message": f"Auto-Pilot mode set to {config.AUTO_APPROVE}."}


@app.get("/webhook")
def verify_webhook(request: Request):
    """Meta WhatsApp Webhook verification endpoint."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_secret = os.getenv("WHATSAPP_VERIFY_TOKEN", "leadmagnet")
    if mode == "subscribe" and token == verify_secret:
        return HTMLResponse(content=challenge)
    return JSONResponse(status_code=403, content={"error": "Verification token mismatch"})


@app.post("/webhook")
async def receive_whatsapp_reply(request: Request):
    """Handles incoming client WhatsApp replies and real-time delivery/read receipts."""
    try:
        body = await request.json()
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        statuses = value.get("statuses", [])

        # ─── 1. Handle Status Receipts (Sent ✓, Delivered ✓✓, Read ✓✓) ───
        if statuses:
            st = statuses[0]
            recipient_phone = st.get("recipient_id", "")
            st_type = (st.get("status") or "").lower()  # sent, delivered, read, failed

            all_leads = db.get_all_leads()
            for l in all_leads:
                if l.phone:
                    clean_db_phone = "".join(filter(str.isdigit, l.phone))
                    clean_rec_phone = "".join(filter(str.isdigit, recipient_phone))
                    if clean_rec_phone.endswith(clean_db_phone[-10:]) or clean_db_phone.endswith(clean_rec_phone[-10:]):
                        if st_type == "read":
                            l.whatsapp_status = "READ"
                        elif st_type == "delivered":
                            l.whatsapp_status = "DELIVERED"
                        elif st_type == "sent" and l.whatsapp_status != "READ" and l.whatsapp_status != "DELIVERED":
                            l.whatsapp_status = "SENT"
                        elif st_type == "failed":
                            l.whatsapp_status = "FAILED"
                        
                        db.upsert_lead(l)
                        break

        # ─── 2. Handle Client Replies ─────────────────────────────────────
        if messages:
            msg = messages[0]
            from_phone = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "")

            all_leads = db.get_all_leads()
            matched_lead = None
            for l in all_leads:
                if l.phone:
                    clean_db_phone = "".join(filter(str.isdigit, l.phone))
                    clean_from_phone = "".join(filter(str.isdigit, from_phone))
                    if clean_from_phone.endswith(clean_db_phone[-10:]) or clean_db_phone.endswith(clean_from_phone[-10:]):
                        matched_lead = l
                        break

            if matched_lead:
                matched_lead.whatsapp_status = "REPLIED"
                matched_lead.status = "REPLIED"
                matched_lead.error_log = f"Client Reply: {msg_text}"
                db.upsert_lead(matched_lead)

                # Sync to Google Sheets
                from sheets_logging.sheets_logger import GoogleSheetsLogger
                sheets = GoogleSheetsLogger()
                sheets.sync_lead(matched_lead)

                # Send instant alert to personal phone
                personal_phone = os.getenv("PERSONAL_NOTIFICATION_PHONE", "")
                if personal_phone and config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID:
                    from outreach.whatsapp_sender import format_whatsapp_phone
                    import requests
                    phone_fmt = format_whatsapp_phone(personal_phone)
                    url = f"https://graph.facebook.com/v18.0/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
                    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
                    notif_body = (
                        f"🚨 *NEW CLIENT REPLY RECEIVED!*\n\n"
                        f"🏢 *Business:* {matched_lead.business_name}\n"
                        f"📍 *City:* {matched_lead.city or 'N/A'}\n"
                        f"💬 *Client Message:* \"{msg_text}\"\n"
                        f"📞 *Client Phone:* +{from_phone}\n\n"
                        f"👉 *Tap to Chat:* https://wa.me/{from_phone}"
                    )
                    requests.post(url, headers=headers, json={
                        "messaging_product": "whatsapp",
                        "to": phone_fmt,
                        "type": "text",
                        "text": {"body": notif_body}
                    }, timeout=10)

        return {"status": "EVENT_RECEIVED"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/reject/{lead_id}")
def reject_lead(lead_id: str):
    """Rejects a lead."""
    success, msg = process_lead_decision(lead_id=lead_id, action="R", db=db)
    if success:
        return {"status": "success", "message": msg}
    return JSONResponse(status_code=400, content={"status": "error", "message": msg})




@app.post("/api/followups")
def trigger_followups(force: bool = True):
    """Triggers follow-up evaluation and generation."""
    engine = FollowupEngine(db=db)
    results = engine.evaluate_and_process_followups(force=force)
    msg = f"Generated {len(results)} new follow-up messages for non-responding leads." if results else "No eligible leads currently due for follow-ups."
    return {"status": "success", "processed_count": len(results), "message": msg, "results": results}


@app.post("/api/sync-sheets")
def sync_to_sheets():
    """Syncs all discovered leads from the database to the connected Google Sheet."""
    from sheets_logging.sheets_logger import GoogleSheetsLogger
    sheets = GoogleSheetsLogger()
    try:
        success, fail = sheets.sync_all_leads(db=db)
        total = success + fail
        if success > 0:
            return {
                "status": "success",
                "message": f"✅ Synced {success}/{total} leads to Google Sheets successfully!",
                "synced": success,
                "failed": fail
            }
        else:
            return JSONResponse(status_code=500, content={
                "status": "error",
                "message": f"❌ Google Sheets sync failed. Check credentials or Sheet permissions. ({fail} leads saved to local queue).",
                "synced": 0,
                "failed": fail
            })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "error",
            "message": f"❌ Sheets sync error: {str(e)}"
        })


@app.post("/api/discover")
def trigger_discovery(city: str, business_type: str, max_leads: int = 10, background_tasks: BackgroundTasks = None):
    """Triggers business discovery for a specific city and business type."""
    from main import run_pipeline
    city_clean = city.strip()
    type_clean = business_type.strip()
    if not city_clean or not type_clean:
        return JSONResponse(status_code=400, content={"status": "error", "message": "City and business_type are required"})
    
    if background_tasks:
        background_tasks.add_task(run_pipeline, city=city_clean, business_type=type_clean, max_leads=max_leads, interactive=False)
    else:
        run_pipeline(city=city_clean, business_type=type_clean, max_leads=max_leads, interactive=False)

    return {
        "status": "success", 
        "message": f"Started lead discovery for '{type_clean}' in '{city_clean}' (max {max_leads} leads). Refresh dashboard in a few seconds."
    }


@app.get("/api/logs")
def get_logs():
    """Returns recent log entries for the live activity stream."""
    log_file = PROJECT_ROOT / "errors.log"
    logs = []
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                logs = [line.strip() for line in lines[-20:] if line.strip()]
        except Exception:
            pass
    if not logs:
        logs = [
            f"[INFO] System initialized. Ready to process leads.",
            f"[INFO] DRY RUN mode active. Outreach will log safely without sending real messages."
        ]
    return {"logs": logs}


@app.post("/api/stage/{stage_name}")
def trigger_stage(stage_name: str, city: str = "Vadodara", category: str = "restaurants", background_tasks: BackgroundTasks = None):
    """Triggers an individual pipeline stage."""
    from discovery.serpapi_search import discover_leads
    from processing.deduplicate import process_and_deduplicate_leads
    from processing.website_checker import verify_leads_websites
    from processing.lead_scorer import score_and_qualify_leads
    from ai.personalizer import personalize_qualified_leads
    from demo.url_generator import process_demo_urls
    from approval.approval_queue import populate_approval_queue
    from outreach.email_sender import send_approved_emails
    from outreach.whatsapp_sender import send_approved_whatsapp_messages

    stg = stage_name.lower()
    msg = ""

    if stg == "discover":
        res = discover_leads(city=city, business_type=category, max_results=10, db=db)
        leads_cnt = len(res.get("leads", []))
        skipped = res.get("skipped_count", 0)
        msg = f"Stage 1 Complete: Discovered {leads_cnt} new leads for '{category}' in '{city}' ({skipped} existing leads skipped)."
    elif stg == "verify":
        res = verify_leads_websites(batch_size=10, db=db)
        msg = f"Stage 2 & 3 Complete: Verified websites for {len(res)} leads."
    elif stg == "score":
        res = score_and_qualify_leads(db=db)
        msg = f"Stage 4 Complete: Scored {len(res)} verified leads and assigned HOT/WARM tiers."
    elif stg == "ai_copy":
        res = personalize_qualified_leads(db=db)
        msg = f"Stage 5 Complete: Generated AI email & WhatsApp copy for {len(res)} leads."
    elif stg == "demos":
        res = process_demo_urls(db=db)
        msg = f"Stage 6 Complete: Generated interactive demo pages for {len(res)} leads."
    elif stg == "approval":
        all_leads = db.get_all_leads()
        res = populate_approval_queue(leads=all_leads, db=db)
        msg = f"Stage 8 Complete: Populated Human Approval Queue with {len(res)} pending records."
    elif stg == "outreach":
        e_res = send_approved_emails(db=db)
        w_res = send_approved_whatsapp_messages(db=db)
        msg = f"Stage 9 Complete: Dispatched outreach ({len(e_res)} emails, {len(w_res)} WhatsApp messages)."
    elif stg == "full":
        from main import run_pipeline
        run_pipeline(city=city, business_type=category, max_leads=10, interactive=False)
        msg = f"Full Pipeline Execution Complete for '{category}' in '{city}'."

    stats = {
        "total_leads": len(db.get_all_leads()),
        "hot_leads": len([l for l in db.get_all_leads() if l.lead_tier == "HOT"]),
        "warm_leads": len([l for l in db.get_all_leads() if l.lead_tier == "WARM"]),
        "demo_ready": len([l for l in db.get_all_leads() if l.demo_status == "READY"]),
        "pending_approval": len([l for l in db.get_all_leads() if l.approval_status in ("PENDING_APPROVAL", "PENDING")]),
        "outreach_sent": len([l for l in db.get_all_leads() if l.email_status in ("SENT", "DRY_RUN_SENT")])
    }

    return {"status": "success", "message": msg, "stats": stats}


@app.get("/api/followups/list")
def list_followups():
    """Returns all leads that have had follow-ups generated, with their follow-up details."""
    all_leads = db.get_all_leads()
    followup_leads = []
    for lead in all_leads:
        if lead.followup_count and lead.followup_count > 0:
            followup_leads.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "email": lead.email,
                "followup_count": lead.followup_count,
                "status": lead.status,
                "email_status": lead.email_status,
                "last_followup_at": lead.last_followup_at,
                "last_contacted_at": lead.last_contacted_at,
                "email_message": lead.email_message or "",
                "whatsapp_message": lead.whatsapp_message or "",
                "demo_url": lead.demo_url or "",
                "approval_status": lead.approval_status,
            })
    # Also include SENT leads that haven't had follow-ups yet (upcoming)
    upcoming = []
    for lead in all_leads:
        if lead.email_status in ("SENT", "DRY_RUN_SENT") and (not lead.followup_count or lead.followup_count == 0):
            upcoming.append({
                "lead_id": lead.lead_id,
                "business_name": lead.business_name,
                "email": lead.email,
                "followup_count": 0,
                "status": lead.status,
                "email_status": lead.email_status,
                "last_contacted_at": lead.last_contacted_at,
                "last_followup_at": None,
                "email_message": "",
                "whatsapp_message": "",
                "demo_url": lead.demo_url or "",
                "approval_status": lead.approval_status,
            })
    return {"sent_followups": followup_leads, "upcoming_followups": upcoming}


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND AUTO FOLLOW-UP SCHEDULER
# Runs every 4 hours. In LIVE mode, auto-dispatches due follow-ups.
# In DRY RUN mode, generates previews only.
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/cron/followups")
def vercel_cron_trigger_followups(request: Request):
    """Vercel Cron endpoint to trigger followups every 4 hours without background thread."""
    # Vercel sends a specific authorization header for crons
    # You can secure this further if you like, for now it allows the cron to hit it.
    engine = FollowupEngine(db=db)
    results = engine.evaluate_and_process_followups(force=False)
    
    if results and not config.DRY_RUN:
        from outreach.email_sender import send_approved_emails
        from outreach.whatsapp_sender import send_approved_whatsapp_messages
        dispatched = 0
        for item in results:
            lead = db.get_lead_by_id(item["lead_id"])
            if lead:
                send_approved_emails(leads=[lead], db=db)
                send_approved_whatsapp_messages(leads=[lead], db=db)
                dispatched += 1
        return {"status": "success", "message": f"Cron: Dispatched {dispatched} follow-ups."}
    
    return {"status": "success", "message": f"Cron completed. Generated {len(results)} follow-ups (Not dispatched)."}



def _auto_followup_scheduler():
    """Background thread: checks every 4 hours and auto-sends due follow-ups."""
    import logging
    scheduler_logger = logging.getLogger("AutoFollowupScheduler")
    # Wait 30 seconds after server boot before first check
    time.sleep(30)
    while True:
        try:
            scheduler_logger.info("[AUTO FOLLOWUP] Running scheduled follow-up evaluation...")
            engine = FollowupEngine(db=db)
            results = engine.evaluate_and_process_followups(force=False)

            if results:
                scheduler_logger.info(f"[AUTO FOLLOWUP] {len(results)} follow-ups generated.")
                if not config.DRY_RUN:
                    # LIVE MODE: auto-dispatch generated follow-ups via email & WhatsApp
                    from outreach.email_sender import send_approved_emails
                    from outreach.whatsapp_sender import send_approved_whatsapp_messages
                    for item in results:
                        lead = db.get_lead_by_id(item["lead_id"])
                        if lead:
                            e_res = send_approved_emails(leads=[lead], db=db)
                            w_res = send_approved_whatsapp_messages(leads=[lead], db=db)
                            scheduler_logger.info(
                                f"[AUTO FOLLOWUP][LIVE] Follow-up #{lead.followup_count} dispatched for "
                                f"'{lead.business_name}' ({len(e_res)} email, {len(w_res)} WA)."
                            )
                else:
                    scheduler_logger.info("[AUTO FOLLOWUP][DRY RUN] Follow-ups generated (not dispatched).")
            else:
                scheduler_logger.info("[AUTO FOLLOWUP] No leads currently due for follow-ups.")

        except Exception as ex:
            import logging
            logging.getLogger("AutoFollowupScheduler").error(f"[AUTO FOLLOWUP] Scheduler error: {ex}")

        # Sleep 4 hours before next check
        time.sleep(4 * 60 * 60)


def _open_browser_when_ready(url: str):
    time.sleep(1.2)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def start_server(port: int = 8001):
    """Starts the web dashboard FastAPI server and the background follow-up scheduler."""
    # Start auto follow-up scheduler in a daemon background thread only if not on Vercel
    if not os.getenv("VERCEL_ENV"):
        scheduler_thread = threading.Thread(target=_auto_followup_scheduler, daemon=True, name="AutoFollowupScheduler")
        scheduler_thread.start()
        print(f"[AUTO FOLLOWUP] Background scheduler started (runs every 4 hours).")
    else:
        print("[AUTO FOLLOWUP] Vercel environment detected. Relying on Vercel Cron instead of background thread.")
    
    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print(f"🚀 Lead Magnet Dashboard running at: {url}")
    print(f"🌐 Opening {url} in your default browser...")
    print("=" * 60)
    
    # Auto-open default browser if not on Vercel
    if not os.getenv("VERCEL_ENV"):
        browser_thread = threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True)
        browser_thread.start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    start_server(8001)

