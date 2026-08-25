import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Config:
    """Application Configuration loaded from environment variables."""
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    SERPAPI_KEY: str = os.getenv("SERPAPI_KEY", "")
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_CREDS_PATH: str = os.getenv("GOOGLE_CREDS_PATH", "./google_creds.json")
    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
    SENDER_NAME: str = os.getenv("SENDER_NAME", "")
    GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")
    DEMO_BASE_URL: str = os.getenv("DEMO_BASE_URL", "http://localhost:8000/preview")
    DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    AUTO_APPROVE: bool = os.getenv("AUTO_APPROVE", "true").lower() in ("true", "1", "yes")
    MAX_LEADS: int = int(os.getenv("MAX_LEADS", "10"))

    
    # Rate Limiting Configuration
    MAX_EMAILS_PER_HOUR: int = int(os.getenv("MAX_EMAILS_PER_HOUR", "10"))
    MAX_WHATSAPP_PER_HOUR: int = int(os.getenv("MAX_WHATSAPP_PER_HOUR", "20"))
    
    # WhatsApp Meta Cloud API Credentials
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    
    # Follow-up Schedule Configuration
    FOLLOWUP_DAYS_STAGE1: int = int(os.getenv("FOLLOWUP_DAYS_STAGE1", "3"))
    FOLLOWUP_DAYS_STAGE2: int = int(os.getenv("FOLLOWUP_DAYS_STAGE2", "7"))
    MAX_FOLLOWUPS: int = int(os.getenv("MAX_FOLLOWUPS", "2"))

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_PATH: str = str(BASE_DIR / "leads.db")

config = Config()
