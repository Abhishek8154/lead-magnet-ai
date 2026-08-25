"""
Direct Google Sheets push script - bypasses OAuth browser flow.
Opens a URL in the browser for you to manually authorize, then uses the token.
Run: python push_to_sheets.py
"""
import sys
import os
import json
import csv
import io
import webbrowser
import urllib.parse
import http.server
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CREDS_PATH = str(PROJECT_ROOT / "google_creds.json")
TOKEN_PATH = PROJECT_ROOT / "logs" / "google_oauth_token.json"
os.makedirs(TOKEN_PATH.parent, exist_ok=True)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

print("=" * 60)
print("  LEAD MAGNET -> GOOGLE SHEETS DIRECT SYNC")
print("=" * 60)
print()

# Step 1: Load all leads from database
from database import Database
from sheets_logging.sheets_logger import LEADS_HEADERS

db = Database()
db.init_db()
leads = db.get_all_leads()
print(f"[INFO] Loaded {len(leads)} leads from database.")

# Step 2: Authenticate
import pickle
from google.auth.transport.requests import Request

creds = None

# Try loading cached token
if TOKEN_PATH.exists():
    try:
        with open(TOKEN_PATH, "rb") as tf:
            creds = pickle.load(tf)
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Refreshing expired token...")
            creds.refresh(Request())
            with open(TOKEN_PATH, "wb") as tf:
                pickle.dump(creds, tf)
        if creds and creds.valid:
            print("[OK] Using cached OAuth token.")
    except Exception as e:
        print(f"[WARN] Could not use cached token: {e}")
        creds = None

if not creds or not creds.valid:
    # Use InstalledAppFlow with console mode as fallback
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    print()
    print("[ACTION] Starting Google OAuth login...")
    print("         A browser window will open. Please:")
    print("         1. Select your Google account")
    print("         2. Click 'Allow' to grant Sheets access")
    print()
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
        
        # Try browser flow first
        try:
            creds = flow.run_local_server(port=8080, open_browser=True, prompt='select_account')
        except Exception:
            # Fallback to console flow
            print("[FALLBACK] Browser could not open. Using console flow...")
            print()
            auth_url, _ = flow.authorization_url(prompt='consent')
            print("PLEASE OPEN THIS URL IN YOUR BROWSER:")
            print()
            print(auth_url)
            print()
            code = input("After authorizing, paste the authorization code here: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials
        
        with open(TOKEN_PATH, "wb") as tf:
            pickle.dump(creds, tf)
        print("[OK] OAuth login successful! Token saved.")
    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}")
        sys.exit(1)

# Step 3: Push all leads to Google Sheets
import gspread

print()
print("[INFO] Connecting to Google Sheets...")

try:
    client = gspread.authorize(creds)
    
    from config import config
    sheet_id = config.GOOGLE_SHEET_ID
    
    spreadsheet = client.open_by_key(sheet_id)
    print(f"[OK] Connected to sheet: '{spreadsheet.title}'")
    
    # Get or create Leads worksheet
    try:
        ws = spreadsheet.worksheet("Leads")
        print("[INFO] Found existing 'Leads' tab. Clearing and re-syncing all data...")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        print("[INFO] Creating new 'Leads' tab...")
        ws = spreadsheet.add_worksheet(title="Leads", rows=500, cols=30)
    
    # Build all rows
    rows = [LEADS_HEADERS]
    for lead in leads:
        rows.append([
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
            (lead.email_message or "")[:500],  # truncate long messages
            (lead.whatsapp_message or "")[:300],
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
    
    print(f"[INFO] Uploading {len(leads)} leads to Google Sheets...")
    ws.update("A1", rows)
    
    # Format header row bold
    try:
        ws.format("A1:Z1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.1, "green": 0.1, "blue": 0.2}
        })
    except Exception:
        pass  # Formatting is optional
    
    print()
    print("=" * 60)
    print(f"  [OK] SUCCESS! {len(leads)} leads synced to Google Sheets!")
    print(f"     Sheet: {spreadsheet.title}")
    print(f"     Tab: Leads")
    print("=" * 60)
    print()
    print(f"  Open: https://docs.google.com/spreadsheets/d/{sheet_id}")
    print()

except Exception as e:
    print(f"[ERROR] Failed to sync to Google Sheets: {e}")
    
    # Export to CSV as fallback
    csv_path = PROJECT_ROOT / "leads_export.csv"
    print()
    print(f"[FALLBACK] Exporting to CSV: {csv_path}")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LEADS_HEADERS)
        for lead in leads:
            writer.writerow([
                lead.lead_id, lead.business_name, lead.category or "",
                lead.city or "", lead.phone or "", lead.email or "",
                lead.address or "", lead.website_url or "",
                lead.website_status or "", lead.lead_score or 0,
                lead.lead_tier or "", lead.qualification_reason or "",
                lead.demo_url or "", lead.demo_status or "",
                (lead.email_message or "")[:200],
                (lead.whatsapp_message or "")[:200],
                lead.approval_status or "", lead.email_status or "",
                lead.whatsapp_status or "", lead.status or "",
                lead.created_at or ""
            ])
    print(f"[OK] CSV saved! Import it into Google Sheets manually.")
    print(f"     File: {csv_path}")
    sys.exit(1)
