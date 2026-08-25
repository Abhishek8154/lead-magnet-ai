import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import gspread
from config import config
from database import Database
from models import Lead
from utils.logger import get_logger

logger = get_logger("SheetsLogger")

# Local fallback queue file
LOCAL_QUEUE_FILE = Path(__file__).resolve().parent.parent / "logs" / "sheets_sync_queue.json"

# OAuth token cache file – stored next to credentials
TOKEN_CACHE_FILE = Path(__file__).resolve().parent.parent / "logs" / "google_oauth_token.json"

# Column headers for "Leads" sheet tab (26 columns)
LEADS_HEADERS = [
    "Lead ID", "Business Name", "Category", "City", "Phone", "Email",
    "Address", "Website", "Website Status", "Lead Score", "Lead Tier",
    "Qualification Reason", "Demo URL", "Demo Status", "Email Message",
    "WhatsApp Message", "Approval Status", "Email Status", "WhatsApp Status",
    "First Contacted At", "Last Contacted At", "Status", "Source",
    "Created At", "Updated At", "Error"
]

# Column headers for "Runs" sheet tab (9 columns)
RUNS_HEADERS = [
    "run_date", "city", "business_type", "discovered",
    "qualified", "hot", "warm", "demo_ready", "errors"
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def _load_creds_file(creds_path: str):
    """
    Loads Google credentials from the JSON file.
    Supports both:
    - Service Account JSON  (has key 'type': 'service_account')
    - OAuth 2.0 Web/Installed Client JSON  (has key 'web' or 'installed')
    Returns a gspread-authorised client or raises an error.
    """
    from google.oauth2 import credentials as google_credentials

    with open(creds_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # ─── Service Account ───────────────────────────────────────────────────
    if raw.get("type") == "service_account":
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        logger.info("[Google Sheets] Authorised via Service Account.")
        return client

    # ─── OAuth 2.0 Web / Installed Client ──────────────────────────────────
    client_data = raw.get("web") or raw.get("installed")
    if not client_data:
        raise ValueError(
            "google_creds.json is in an unrecognised format. "
            "Expected 'type':'service_account', 'web', or 'installed' key."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import pickle

    TOKEN_FILE = TOKEN_CACHE_FILE
    os.makedirs(TOKEN_FILE.parent, exist_ok=True)

    creds = None

    # Try loading cached token
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "rb") as tf:
                creds = pickle.load(tf)
            logger.info("[Google Sheets] Loaded cached OAuth token.")
        except Exception:
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("[Google Sheets] Refreshed expired OAuth token.")
            with open(TOKEN_FILE, "wb") as tf:
                pickle.dump(creds, tf)
        except Exception as e:
            logger.warning(f"[Google Sheets] Token refresh failed: {e}. Re-authenticating...")
            creds = None

    # First-time authentication
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as tf:
            pickle.dump(creds, tf)
        logger.info("[Google Sheets] OAuth login complete. Token cached for future runs.")

    client = gspread.authorize(creds)
    logger.info("[Google Sheets] Authorised via OAuth 2.0.")
    return client


class GoogleSheetsLogger:
    def __init__(self):
        self.creds_path = config.GOOGLE_CREDS_PATH
        self.sheet_id = config.GOOGLE_SHEET_ID
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None

    def connect(self, retries: int = 3, delay: float = 2.0) -> bool:
        """Connects to Google Sheets API using credentials file with automatic retry on transient errors."""
        if not self.sheet_id or self.sheet_id == "your-sheet-id-from-url":
            logger.warning("[Google Sheets] GOOGLE_SHEET_ID is missing or unconfigured.")
            return False

        if not os.path.exists(self.creds_path):
            logger.warning(f"[Google Sheets] Credentials file not found at '{self.creds_path}'.")
            return False

        import time
        for attempt in range(1, retries + 1):
            try:
                self.client = _load_creds_file(self.creds_path)
                self.spreadsheet = self.client.open_by_key(self.sheet_id)
                logger.info(f"Connected successfully to Google Sheet ID: '{self.sheet_id}'.")
                return True
            except Exception as e:
                logger.warning(f"[Google Sheets Connection Attempt {attempt}/{retries} Failed] {e}")
                if attempt < retries:
                    time.sleep(delay * attempt)

        logger.error(f"[Google Sheets Connection Error] Failed to connect after {retries} attempts.")
        return False

    def get_or_create_worksheet(self, title: str, headers: List[str]) -> Optional[gspread.Worksheet]:
        """Gets or creates a worksheet tab by title and ensures column headers exist."""
        if not self.spreadsheet:
            if not self.connect():
                return None

        try:
            try:
                worksheet = self.spreadsheet.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                logger.info(f"Worksheet '{title}' not found. Creating new tab...")
                worksheet = self.spreadsheet.add_worksheet(title=title, rows=100, cols=len(headers))
                worksheet.append_row(headers)
                return worksheet

            # Check headers
            existing_headers = worksheet.row_values(1)
            if not existing_headers:
                worksheet.append_row(headers)
            return worksheet
        except Exception as e:
            logger.error(f"[Google Sheets Error] Failed getting worksheet '{title}': {e}")
            return None

    def lead_to_row(self, lead: Lead) -> List[Any]:
        """Formats a Lead dataclass into the 26-column list for Google Sheets."""
        return [
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
            lead.email_message or "",
            lead.whatsapp_message or "",
            lead.approval_status or "PENDING",
            lead.email_status or "NOT_SENT",
            lead.whatsapp_status or "NOT_SENT",
            getattr(lead, "first_contacted_at", ""),
            getattr(lead, "last_contacted_at", ""),
            lead.status or "",
            lead.source_url or "",
            lead.created_at or "",
            lead.updated_at or "",
            lead.error_log or ""
        ]

    def save_locally_to_queue(self, lead_dict: Dict[str, Any]):
        """Saves unsynced lead records locally to queue file when API is unavailable."""
        os.makedirs(LOCAL_QUEUE_FILE.parent, exist_ok=True)
        queue_data = []

        if LOCAL_QUEUE_FILE.exists():
            try:
                with open(LOCAL_QUEUE_FILE, "r", encoding="utf-8") as f:
                    queue_data = json.load(f)
            except Exception:
                queue_data = []

        # Deduplicate queue by lead_id
        lead_id = lead_dict.get("lead_id")
        queue_data = [item for item in queue_data if item.get("lead_id") != lead_id]
        queue_data.append(lead_dict)

        with open(LOCAL_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue_data, f, indent=2)

        logger.info(f"Saved lead '{lead_dict.get('business_name')}' locally to sheets queue file.")

    def sync_lead(self, lead: Lead) -> bool:
        """
        Syncs a lead to the 'Leads' worksheet tab:
        - Finds row by Lead ID (Column A)
        - Updates existing row if found, appends new row if not found.
        """
        row_values = self.lead_to_row(lead)
        worksheet = self.get_or_create_worksheet("Leads", LEADS_HEADERS)

        if not worksheet:
            logger.warning(f"Google Sheets API unavailable. Saving lead '{lead.business_name}' to local fallback queue.")
            self.save_locally_to_queue(lead.to_dict())
            return False

        try:
            # Search Column A (Lead ID)
            cell = worksheet.find(lead.lead_id, in_column=1)
            if cell:
                # Update existing row
                row_idx = cell.row
                worksheet.update(f"A{row_idx}:Z{row_idx}", [row_values])
                logger.info(f"[Google Sheets] Updated existing row {row_idx} for lead '{lead.business_name}' (ID: {lead.lead_id}).")
            else:
                # Append new row
                worksheet.append_row(row_values)
                logger.info(f"[Google Sheets] Appended new row for lead '{lead.business_name}' (ID: {lead.lead_id}).")

            return True
        except Exception as e:
            logger.error(f"[Google Sheets Sync Error] Failed to sync lead '{lead.business_name}': {e}")
            self.save_locally_to_queue(lead.to_dict())
            return False

    def sync_all_leads(self, db: Optional[Database] = None) -> Tuple[int, int]:
        """Syncs all leads from database to Google Sheets in a single batch."""
        if db is None:
            db = Database()
            db.init_db()

        leads = db.get_all_leads()
        success_count = 0
        fail_count = 0

        if not leads:
            logger.info("[Google Sheets] No leads found to sync.")
            return 0, 0

        worksheet = self.get_or_create_worksheet("Leads", LEADS_HEADERS)
        if not worksheet:
            logger.warning("[Google Sheets] Could not connect for bulk sync. Saving all leads to local queue.")
            for lead in leads:
                self.save_locally_to_queue(lead.to_dict())
            return 0, len(leads)

        logger.info(f"[Google Sheets] Starting bulk sync for {len(leads)} leads...")

        try:
            # Fetch all existing Lead IDs from column A for fast lookup
            existing_ids = worksheet.col_values(1)  # ["Lead ID", "lead-001", "lead-002", ...]
            id_to_row = {v: i + 1 for i, v in enumerate(existing_ids)}

            rows_to_append = []
            rows_to_update = []

            for lead in leads:
                row = self.lead_to_row(lead)
                if lead.lead_id in id_to_row:
                    rows_to_update.append((id_to_row[lead.lead_id], row))
                else:
                    rows_to_append.append(row)

            # Batch append new leads
            if rows_to_append:
                worksheet.append_rows(rows_to_append)
                logger.info(f"[Google Sheets] Appended {len(rows_to_append)} new leads.")
                success_count += len(rows_to_append)

            # Update existing leads one-by-one (gspread batch_update for rows)
            for row_idx, row_values in rows_to_update:
                try:
                    worksheet.update(f"A{row_idx}:Z{row_idx}", [row_values])
                    success_count += 1
                except Exception as e:
                    logger.error(f"[Google Sheets] Failed to update row {row_idx}: {e}")
                    fail_count += 1

            logger.info(f"[Google Sheets] Bulk sync complete: {success_count} synced, {fail_count} failed.")
        except Exception as e:
            logger.error(f"[Google Sheets] Bulk sync error: {e}")
            for lead in leads:
                self.save_locally_to_queue(lead.to_dict())
            fail_count = len(leads)

        return success_count, fail_count

    def log_run_summary(
        self,
        city: str,
        business_type: str,
        stats: Optional[Dict[str, int]] = None
    ) -> bool:
        """
        Logs a summary row in the 'Runs' worksheet tab:
        run_date, city, business_type, discovered, qualified, hot, warm, demo_ready, errors
        """
        worksheet = self.get_or_create_worksheet("Runs", RUNS_HEADERS)

        stats = stats or {}
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        run_row = [
            now_str,
            city,
            business_type,
            stats.get("discovered", 0),
            stats.get("qualified", 0),
            stats.get("hot", 0),
            stats.get("warm", 0),
            stats.get("demo_ready", 0),
            stats.get("errors", 0)
        ]

        if not worksheet:
            logger.warning("Google Sheets API unavailable for logging run summary. Saving summary locally.")
            return False

        try:
            worksheet.append_row(run_row)
            logger.info(f"[Google Sheets] Logged run summary to 'Runs' tab for {business_type} in {city}.")
            return True
        except Exception as e:
            logger.error(f"[Google Sheets Error] Failed logging run summary: {e}")
            return False
