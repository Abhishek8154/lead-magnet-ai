import argparse
import sys
import os
from typing import Dict, Any
from config import config
from database import Database
from models import Lead, LeadStatus
from discovery.serpapi_search import discover_leads
from processing.deduplicate import process_and_deduplicate_leads
from processing.website_checker import verify_leads_websites
from processing.lead_scorer import score_and_qualify_leads
from ai.personalizer import personalize_qualified_leads
from demo.url_generator import process_demo_urls
from approval.approval_queue import populate_approval_queue
from approval.approval_viewer import review_pending_approvals_interactive
from outreach.email_sender import send_approved_emails
from outreach.whatsapp_sender import send_approved_whatsapp_messages
from sheets_logging.sheets_logger import GoogleSheetsLogger
from utils.logger import get_logger
from utils.error_handler import log_error

logger = get_logger("Orchestrator")


def run_pipeline(city: str, business_type: str, max_leads: int, interactive: bool = True):
    """Executes the complete Lead Magnet AI pipeline end-to-end."""
    print("\n" + "="*95)
    print("      LEAD MAGNET AI — END-TO-END MASTER AUTOMATION PIPELINE      ")
    print("="*95)
    print(f"Target City         : {city}")
    print(f"Business Category   : {business_type}")
    print(f"Max Leads Limit     : {max_leads}")
    print(f"DRY RUN Mode        : {config.DRY_RUN} (Safety Protection)")
    print("="*95 + "\n")

    db = Database()
    db.init_db()
    sheets_logger = GoogleSheetsLogger()

    # Stage 1: Discovery via SerpAPI
    logger.info("--- Stage 1/10: Business Discovery (SerpAPI) ---")
    try:
        discovery_result = discover_leads(city=city, business_type=business_type, max_results=max_leads, db=db)
        discovered_leads = discovery_result.get("leads", [])
        print(f"[Stage 1 OK] Discovered {len(discovered_leads)} businesses matching '{business_type} in {city}'.")
    except Exception as e:
        log_error(e, module_name="DiscoveryStage")
        print(f"[Stage 1 WARNING] Discovery error: {e}")

    # Stage 2: Normalization & Deduplication
    logger.info("--- Stage 2/10: Normalization & Deduplication ---")
    try:
        all_leads = db.get_all_leads()
        target_leads = [l for l in all_leads if l.city and l.city.lower() == city.lower()]
        dedup_summary = process_and_deduplicate_leads(leads=target_leads, db=db)
        print(f"[Stage 2 OK] Deduplication completed: {dedup_summary['unique_count']} unique leads, {dedup_summary['duplicate_count']} duplicates removed.")
    except Exception as e:
        log_error(e, module_name="DedupStage")

    # Stage 3: Website Verification (5 at a time with delay)
    logger.info("--- Stage 3/10: Website Verification ---")
    try:
        unprocessed_web = db.get_unprocessed_leads_for_stage("WEBSITE_CHECK")
        unprocessed_web_city = [l for l in unprocessed_web if l.city and l.city.lower() == city.lower()]
        
        if unprocessed_web_city:
            print(f"[Stage 3] Verifying websites for {len(unprocessed_web_city)} leads...")
            for idx, lead in enumerate(unprocessed_web_city, 1):
                print(f"Processing lead {idx}/{len(unprocessed_web_city)}: {lead.business_name}...")
            
            verify_leads_websites(batch_size=len(unprocessed_web_city), db=db, delay_seconds=1.0)
            print(f"[Stage 3 OK] Website verification batch complete.")
        else:
            print("[Stage 3 OK] All leads already completed website verification (Resumed).")
    except Exception as e:
        log_error(e, module_name="WebsiteCheckStage")

    # Stage 4: Scoring & Qualification
    logger.info("--- Stage 4/10: Lead Scoring & Qualification ---")
    try:
        unprocessed_scoring = db.get_unprocessed_leads_for_stage("SCORING")
        unprocessed_scoring_city = [l for l in unprocessed_scoring if l.city and l.city.lower() == city.lower()]

        if unprocessed_scoring_city:
            print(f"[Stage 4] Scoring {len(unprocessed_scoring_city)} verified leads...")
            score_and_qualify_leads(leads=unprocessed_scoring_city, db=db)
            print(f"[Stage 4 OK] Lead scoring complete.")
        else:
            print("[Stage 4 OK] All leads already scored and qualified (Resumed).")
    except Exception as e:
        log_error(e, module_name="ScoringStage")

    # Stage 5: AI Personalization (HOT and WARM leads only)
    logger.info("--- Stage 5/10: AI Personalization ---")
    try:
        unprocessed_ai = db.get_unprocessed_leads_for_stage("PERSONALIZATION")
        unprocessed_ai_city = [l for l in unprocessed_ai if l.city and l.city.lower() == city.lower()]

        if unprocessed_ai_city:
            print(f"[Stage 5] Generating AI outreach for {len(unprocessed_ai_city)} QUALIFIED leads...")
            personalize_qualified_leads(leads=unprocessed_ai_city, db=db, delay_seconds=0.5)
            print(f"[Stage 5 OK] AI personalization complete.")
        else:
            print("[Stage 5 OK] All qualified leads already personalized (Resumed).")
    except Exception as e:
        log_error(e, module_name="AIPersonalizationStage")

    # Stage 6: Demo URL Generation
    logger.info("--- Stage 6/10: Demo URL Generation & Verification ---")
    try:
        unprocessed_demo = db.get_unprocessed_leads_for_stage("DEMO_URL")
        unprocessed_demo_city = [l for l in unprocessed_demo if l.city and l.city.lower() == city.lower()]

        if unprocessed_demo_city:
            print(f"[Stage 6] Generating demo URLs for {len(unprocessed_demo_city)} leads...")
            process_demo_urls(leads=unprocessed_demo_city, db=db)
            print(f"[Stage 6 OK] Demo URLs created & verified.")
        else:
            print("[Stage 6 OK] Demo URLs already generated (Resumed).")
    except Exception as e:
        log_error(e, module_name="DemoURLStage")

    # Stage 7: Google Sheets Initial Sync
    logger.info("--- Stage 7/10: Google Sheets Sync ---")
    try:
        sheets_logger.sync_all_leads(db=db)
        print("[Stage 7 OK] Google Sheets leads tab updated.")
    except Exception as e:
        log_error(e, module_name="SheetsSyncStage")

    # Stage 8: Human Approval Queue & Terminal Review
    logger.info("--- Stage 8/10: Human Approval Gate ---")
    try:
        unprocessed_appr = db.get_unprocessed_leads_for_stage("APPROVAL_QUEUE")
        unprocessed_appr_city = [l for l in unprocessed_appr if l.city and l.city.lower() == city.lower()]

        if unprocessed_appr_city:
            populate_approval_queue(leads=unprocessed_appr_city, db=db)

        pending_approvals = db.get_pending_approvals()
        
        # In AUTO_APPROVE (Auto-Pilot) mode, automatically approve HOT and WARM qualified leads
        if getattr(config, "AUTO_APPROVE", True):
            auto_count = 0
            for item in pending_approvals:
                tier = item.get("lead_tier") if isinstance(item, dict) else getattr(item, "lead_tier", "")
                score = item.get("lead_score") if isinstance(item, dict) else getattr(item, "lead_score", 0)
                lead_id = item.get("lead_id") if isinstance(item, dict) else getattr(item, "lead_id", "")
                
                if tier in ("HOT", "WARM") or (score and score >= 60):
                    lead = db.get_lead_by_id(lead_id) if lead_id else None
                    if lead:
                        lead.approval_status = "APPROVED"
                        lead.status = LeadStatus.APPROVED.value
                        db.upsert_lead(lead)
                        auto_count += 1
            print(f"[Stage 8 AUTO-PILOT] Automatically approved {auto_count} qualified leads for outreach.")
        elif pending_approvals and interactive:
            print(f"[Stage 8] Launching terminal review session for {len(pending_approvals)} pending leads...")
            review_pending_approvals_interactive(db=db)
        else:
            print(f"[Stage 8 OK] {len(pending_approvals)} pending approvals queued for Web Dashboard review.")

    except Exception as e:
        log_error(e, module_name="ApprovalStage")

    # Stage 9: Outreach Dispatch (Email & WhatsApp)
    logger.info("--- Stage 9/10: Outreach Dispatch ---")
    try:
        unprocessed_outreach = db.get_unprocessed_leads_for_stage("OUTREACH")
        unprocessed_outreach_city = [l for l in unprocessed_outreach if l.city and l.city.lower() == city.lower()]

        if unprocessed_outreach_city:
            print(f"[Stage 9] Dispatching outreach for {len(unprocessed_outreach_city)} APPROVED leads (DRY_RUN={config.DRY_RUN})...")
            send_approved_emails(leads=unprocessed_outreach_city, db=db)
            send_approved_whatsapp_messages(leads=unprocessed_outreach_city, db=db)
            print("[Stage 9 OK] Outreach dispatch complete.")
        else:
            print("[Stage 9 OK] No approved leads awaiting outreach.")
    except Exception as e:
        log_error(e, module_name="OutreachStage")

    # Stage 10: Calculate Final Metrics & Summary Row Logging
    logger.info("--- Stage 10/10: Final Run Summary & Logging ---")
    final_leads = [l for l in db.get_all_leads() if l.city and l.city.lower() == city.lower()]

    discovered_cnt = len(final_leads)
    dup_cnt = len([l for l in final_leads if l.status == "DUPLICATE"])
    valid_web_cnt = len([l for l in final_leads if l.website_status == "VALID_WEBSITE"])
    no_broken_web_cnt = len([l for l in final_leads if l.website_status in ("NO_WEBSITE", "BROKEN_WEBSITE", "SOCIAL_ONLY", "DIRECTORY_ONLY")])
    hot_cnt = len([l for l in final_leads if l.lead_tier == "HOT"])
    warm_cnt = len([l for l in final_leads if l.lead_tier == "WARM"])
    demo_ready_cnt = len([l for l in final_leads if l.demo_status == "READY"])
    awaiting_appr_cnt = len([l for l in final_leads if l.status == "PENDING_APPROVAL"])
    sent_cnt = len([l for l in final_leads if l.status in ("SENT", "DRY_RUN_SENT")])
    failures_cnt = len([l for l in final_leads if l.status == "FAILED" or l.error_log])

    stats = {
        "discovered": discovered_cnt,
        "qualified": len([l for l in final_leads if l.status in ("QUALIFIED", "PERSONALIZED", "DEMO_READY", "PENDING_APPROVAL", "APPROVED", "SENT", "DRY_RUN_SENT")]),
        "hot": hot_cnt,
        "warm": warm_cnt,
        "demo_ready": demo_ready_cnt,
        "errors": failures_cnt
    }

    # Log summary row to Google Sheets Runs tab
    sheets_logger.log_run_summary(city=city, business_type=business_type, stats=stats)

    print("\n" + "="*95)
    print("                     FINAL PIPELINE SUMMARY METRICS                     ")
    print("="*95)
    print(f"Discovered        : {discovered_cnt} businesses")
    print(f"Duplicates removed: {dup_cnt}")
    print(f"Have websites     : {valid_web_cnt}")
    print(f"No/broken website : {no_broken_web_cnt}")
    print(f"HOT leads         : {hot_cnt}")
    print(f"WARM leads        : {warm_cnt}")
    print(f"Demo URLs ready   : {demo_ready_cnt}")
    print(f"Awaiting approval : {awaiting_appr_cnt}")
    print(f"Sent (or DRY RUN) : {sent_cnt}")
    print(f"Failures          : {failures_cnt}")
    print("="*95 + "\n")


def run_followups():
    """Runs the follow-up management engine to process due follow-ups."""
    print("\n" + "="*95)
    print("         LEAD MAGNET AI — AUTOMATED FOLLOW-UP MANAGEMENT SYSTEM         ")
    print("="*95 + "\n")

    from followup.followup_engine import FollowupEngine
    engine = FollowupEngine()
    results = engine.evaluate_and_process_followups()

    if not results:
        print("[INFO] No leads are currently due for follow-ups.")
        return

    print(f"\n[FOLLOW-UP GENERATED] Created follow-up messages for {len(results)} leads:")
    for idx, r in enumerate(results, 1):
        print(f"\n{'='*45} [{idx}/{len(results)}] {'='*45}")
        print(f"Business Name   : {r['business_name']}")
        print(f"Follow-up Stage : #{r['followup_count']}")
        print(f"Lead Status     : {r['status']}")
        print(f"Approval Status : {r['approval_status']}")
        print("\n--- GENERATED FOLLOW-UP EMAIL ---")
        print(r['email_message'])
        print("\n--- GENERATED FOLLOW-UP WHATSAPP ---")
        print(r['whatsapp_message'])
        print("-" * 90)

    # Launch Approval Gate for Follow-ups
    print("\n[APPROVAL GATE] Launching review queue for generated follow-ups...")
    review_pending_approvals_interactive()


def main():
    parser = argparse.ArgumentParser(description="Lead Magnet AI - Master Outreach Automation System")
    parser.add_argument("--city", type=str, required=False, help="Target city (e.g. Vadodara)")
    parser.add_argument("--type", type=str, required=False, help="Business category (e.g. restaurants)")
    parser.add_argument("--max", type=int, default=config.MAX_LEADS, help="Maximum leads to discover")
    parser.add_argument("--followups", action="store_true", help="Run follow-up management engine for contacted leads")

    args = parser.parse_args()

    if args.followups:
        run_followups()
        return

    city = (args.city or "").strip()
    business_type = (args.type or "").strip()
    max_leads = args.max

    if not city or not business_type:
        print("ERROR: Both --city and --type arguments must be provided when not running --followups.")
        sys.exit(1)

    run_pipeline(city=city, business_type=business_type, max_leads=max_leads)


if __name__ == "__main__":
    main()
