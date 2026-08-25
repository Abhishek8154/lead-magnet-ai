"""
One-time Google OAuth setup script.
Run this ONCE from command line: python setup_google_auth.py
It will open a browser to authorize Google Sheets access,
then cache the token so the dashboard sync works automatically.
"""
import os
import sys
import json
import pickle
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CREDS_PATH = PROJECT_ROOT / "google_creds.json"
TOKEN_PATH = PROJECT_ROOT / "logs" / "google_oauth_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

os.makedirs(TOKEN_PATH.parent, exist_ok=True)

print("=" * 60)
print("  GOOGLE SHEETS - ONE-TIME AUTH SETUP")
print("=" * 60)

if not CREDS_PATH.exists():
    print(f"[ERROR] google_creds.json not found at: {CREDS_PATH}")
    sys.exit(1)

with open(CREDS_PATH) as f:
    raw = json.load(f)

cred_type = "service_account" if raw.get("type") == "service_account" else (
    "web" if "web" in raw else "installed" if "installed" in raw else "unknown"
)
print(f"[INFO] Credential type detected: {cred_type}")

if cred_type == "service_account":
    print("[INFO] Service Account credentials - no OAuth flow needed.")
    print("[INFO] Run sync from dashboard directly.")
    sys.exit(0)

if cred_type == "unknown":
    print("[ERROR] Unrecognised credential format in google_creds.json")
    sys.exit(1)

# OAuth 2.0 flow
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

creds = None

# Check if token already exists
if TOKEN_PATH.exists():
    try:
        with open(TOKEN_PATH, "rb") as tf:
            creds = pickle.load(tf)
        if creds and creds.valid:
            print("[OK] Valid token already exists! No login needed.")
            print(f"     Token file: {TOKEN_PATH}")
            print()
            print("✅ You can now use 'Sync → Google Sheets' from the dashboard!")
            sys.exit(0)
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Token expired - attempting refresh...")
            creds.refresh(Request())
            with open(TOKEN_PATH, "wb") as tf:
                pickle.dump(creds, tf)
            print("[OK] Token refreshed successfully!")
            print()
            print("✅ You can now use 'Sync → Google Sheets' from the dashboard!")
            sys.exit(0)
    except Exception as e:
        print(f"[WARN] Could not load existing token ({e}). Re-authenticating...")
        creds = None

print()
print("[ACTION] Opening browser for Google login...")
print("         Please log in and click ALLOW to grant Sheets access.")
print()

try:
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=8080, prompt='select_account')

    # Save the token
    with open(TOKEN_PATH, "wb") as tf:
        pickle.dump(creds, tf)

    print()
    print("=" * 60)
    print("  ✅ AUTH COMPLETE! Token saved.")
    print(f"     {TOKEN_PATH}")
    print("=" * 60)
    print()
    print("  Now go to your dashboard at http://localhost:8001")
    print("  and click '📊 Sync → Google Sheets' in the sidebar.")
    print()

except Exception as e:
    print(f"[ERROR] Authentication failed: {e}")
    sys.exit(1)
