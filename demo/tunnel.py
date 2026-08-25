import os
import re
import sys
import time
import subprocess
import threading
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from database import Database
from demo.server import generate_slug
from utils.logger import get_logger

logger = get_logger("CloudflareTunnel")

CLOUDFLARED_EXE = PROJECT_ROOT / "cloudflared.exe"
if not CLOUDFLARED_EXE.exists():
    # Check default system location
    alt = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
    if alt.exists():
        CLOUDFLARED_EXE = alt


def update_env_demo_url(public_base_url: str):
    """Updates DEMO_BASE_URL in .env file."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    content = env_path.read_text(encoding="utf-8")
    preview_url = f"{public_base_url.rstrip('/')}/preview"
    
    if "DEMO_BASE_URL=" in content:
        content = re.sub(r"DEMO_BASE_URL=.*", f"DEMO_BASE_URL={preview_url}", content)
    else:
        content += f"\nDEMO_BASE_URL={preview_url}\n"
        
    env_path.write_text(content, encoding="utf-8")
    config.DEMO_BASE_URL = preview_url
    logger.info(f"Updated .env with DEMO_BASE_URL={preview_url}")


def update_database_leads(public_base_url: str):
    """Updates all leads in the database with the public HTTPS demo URL and attractive personalized messages."""
    from ai.personalizer import generate_fallback_messages
    db = Database()
    leads = db.get_all_leads()
    updated = 0
    preview_base = f"{public_base_url.rstrip('/')}/preview"

    for lead in leads:
        slug = generate_slug(lead.business_name, lead.city)
        demo_url = f"{preview_base}/{slug}"
        lead.demo_url = demo_url
        lead.demo_status = "READY"

        fallback_msg = generate_fallback_messages(lead)
        email_text = f"Subject: {fallback_msg['email_subject']}\n\n{fallback_msg['email_body']}".replace("{{DEMO_URL}}", demo_url)
        wa_text = fallback_msg['whatsapp_message'].replace("{{DEMO_URL}}", demo_url)

        lead.email_message = email_text
        lead.whatsapp_message = wa_text

        db.upsert_lead(lead)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE approvals SET email_message = ?, whatsapp_message = ?, demo_url = ? WHERE lead_id = ?",
                (email_text, wa_text, demo_url, lead.lead_id)
            )
            conn.commit()

        updated += 1

    logger.info(f"Updated {updated} leads in database with live public HTTPS demo URLs.")


def start_demo_server_if_needed(port: int = 8001):
    """Checks if web dashboard/demo server is active."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        logger.info(f"Server is already running on port {port}.")
    except Exception:
        import uvicorn
        from web.app import app
        def _run():
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        t = threading.Thread(target=_run, daemon=True, name="DemoServerThread")
        t.start()
        time.sleep(2)
        logger.info(f"Started web app server on port {port}.")


def run_tunnel(port: int = 8001):
    """Launches Cloudflare Tunnel for the web app and updates all lead demo URLs with the public HTTPS address."""
    start_demo_server_if_needed(port)

    logfile = PROJECT_ROOT / "cloudflare.log"
    if logfile.exists():
        try:
            logfile.unlink()
        except Exception:
            pass

    cmd = [str(CLOUDFLARED_EXE), "tunnel", "--url", f"http://127.0.0.1:{port}", "--logfile", str(logfile)]
    logger.info(f"Starting Cloudflare Tunnel on port {port}...")

    process = subprocess.Popen(cmd)

    public_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    # Wait up to 30 seconds for Cloudflare to assign a public domain
    start_time = time.time()
    while time.time() - start_time < 30:
        time.sleep(1)
        if logfile.exists():
            try:
                content = logfile.read_text(encoding="utf-8", errors="ignore")
                match = url_pattern.search(content)
                if match:
                    public_url = match.group(0)
                    break
            except Exception:
                pass

    if public_url:
        print("\n" + "=" * 65)
        print(f"🎉 PUBLIC LIVE HTTPS DEMO BASE URL READY:")
        print(f"👉 {public_url}")
        print("=" * 65 + "\n")
        update_env_demo_url(public_url)
        update_database_leads(public_url)
    else:
        logger.error("Timed out waiting for Cloudflare public URL.")

    # Keep process running
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()


if __name__ == "__main__":
    run_tunnel(8001)

