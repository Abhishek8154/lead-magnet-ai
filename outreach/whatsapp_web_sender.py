import os
import sys
import time
import base64
import urllib.parse
import threading
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from processing.normalize import normalize_phone
from utils.logger import get_logger

logger = get_logger("WhatsAppWebSender")
PROFILE_DIR = PROJECT_ROOT / "logs" / "wa_browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Lock to prevent concurrent browser access to the same profile directory
_browser_lock = threading.Lock()

SESSION_MARKER = PROFILE_DIR / ".wa_authenticated"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage"
]

# Global state for QR code live streaming in dashboard modal
_qr_state = {
    "status": "IDLE",       # IDLE, LOADING, QR_READY, AUTHENTICATED, TIMEOUT, ERROR
    "image_base64": None,   # Data URI or base64 string of the QR code
    "message": ""
}


def format_whatsapp_phone(phone: Optional[str]) -> str:
    """Formats phone number into international format with 91 country code for India."""
    raw_digits = normalize_phone(phone)
    if not raw_digits:
        return ""
    if len(raw_digits) == 10:
        return f"91{raw_digits}"
    return raw_digits


def is_whatsapp_web_logged_in() -> bool:
    """Checks if WhatsApp Web persistent browser session has been authenticated by QR scan."""
    return SESSION_MARKER.exists()


def unlink_whatsapp_web() -> Dict[str, Any]:
    """Unlinks the WhatsApp Web session by removing the authentication marker."""
    global _qr_state
    try:
        if SESSION_MARKER.exists():
            SESSION_MARKER.unlink(missing_ok=True)
        _qr_state = {
            "status": "IDLE",
            "image_base64": None,
            "message": "WhatsApp session unlinked."
        }
        logger.info("WhatsApp Web session unlinked by user.")
        return {"status": "success", "message": "WhatsApp Web session unlinked."}
    except Exception as e:
        logger.error(f"Error unlinking WhatsApp: {e}")
        return {"status": "error", "message": str(e)}


def get_current_qr_state() -> Dict[str, Any]:
    """Returns the current QR code capture state for the dashboard modal."""
    if is_whatsapp_web_logged_in():
        return {
            "status": "AUTHENTICATED",
            "is_linked": True,
            "image_base64": None,
            "message": "WhatsApp Web is linked and ready for automated background sending."
        }
    return {
        "status": _qr_state["status"],
        "is_linked": False,
        "image_base64": _qr_state["image_base64"],
        "message": _qr_state["message"]
    }


def start_live_qr_capture(timeout_seconds: int = 90):
    """
    Background worker that runs Chromium in headless mode, grabs the WhatsApp Web QR code screenshot,
    serves it to the dashboard modal, and waits for the user to scan.
    """
    global _qr_state

    if is_whatsapp_web_logged_in():
        _qr_state = {"status": "AUTHENTICATED", "image_base64": None, "message": "Already linked!"}
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _qr_state = {"status": "ERROR", "image_base64": None, "message": "Playwright is not installed."}
        return

    with _browser_lock:
        _qr_state = {"status": "LOADING", "image_base64": None, "message": "Opening WhatsApp Web and generating QR code..."}
        logger.info("Launching Chromium to capture live WhatsApp Web QR code...")

        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=True,
                    args=BROWSER_ARGS,
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800}
                )
                pages = browser.pages
                page = pages[0] if pages else browser.new_page()
                page.goto("https://web.whatsapp.com", timeout=45000, wait_until="domcontentloaded")

                start_time = time.time()
                qr_captured = False
                qr_selectors = [
                    "div[data-ref]",
                    "canvas",
                    "[data-testid='qrcode']",
                    "div._akau canvas",
                    "div._akau",
                    "div[aria-label*='QR']"
                ]

                while time.time() - start_time < timeout_seconds:
                    time.sleep(1.0)

                    # Check for "Reload QR code" button if expired
                    try:
                        reload_btn = page.locator("button:has-text('Click to reload QR code'), button:has-text('Reload QR code'), [data-testid='reload-qr']")
                        if reload_btn.count() > 0 and reload_btn.first.is_visible():
                            logger.info("Reloading expired WhatsApp QR code...")
                            reload_btn.first.click()
                            time.sleep(1.0)
                    except Exception:
                        pass

                    # Check if authenticated or in progress of syncing after mobile scan
                    auth_selectors = [
                        "#pane-side",
                        "[data-testid='chat-list']",
                        "div[aria-label='Chat list']",
                        "div[aria-label='Search text']",
                        "header[data-testid='chatlist-header']",
                        "div[data-testid='intro-title']",
                        "div[role='textbox']",
                        "progress",
                        "button[aria-label='Menu']",
                        "button[aria-label='New chat']"
                    ]
                    
                    is_authenticated = False
                    for auth_sel in auth_selectors:
                        if page.locator(auth_sel).count() > 0:
                            is_authenticated = True
                            break

                    # Also check if QR disappeared after being captured (user scanned it)
                    if qr_captured and not is_authenticated:
                        canvases = page.locator("canvas, div[data-ref]").count()
                        if canvases == 0:
                            logger.info("QR code disappeared from page - mobile scan detected! Finalizing session...")
                            time.sleep(3.0)
                            is_authenticated = True

                    if is_authenticated:
                        # Wait for IndexedDB session tokens and state to fully persist to disk
                        time.sleep(5.0)
                        SESSION_MARKER.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ"))
                        _qr_state = {
                            "status": "AUTHENTICATED",
                            "image_base64": None,
                            "message": "🎉 WhatsApp Web successfully linked!"
                        }
                        logger.info("WhatsApp Web authenticated successfully via live QR scan! Session stored.")
                        time.sleep(1.0)
                        browser.close()
                        return

                    # Try capturing the QR Code element if not already captured
                    for sel in qr_selectors:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.first.is_visible():
                                screenshot_bytes = loc.first.screenshot()
                                if len(screenshot_bytes) > 500:  # Ensure valid image
                                    b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                                    _qr_state = {
                                        "status": "QR_READY",
                                        "image_base64": f"data:image/png;base64,{b64}",
                                        "message": "Point your phone camera / WhatsApp scanner at this QR code."
                                    }
                                    qr_captured = True
                                    break
                        except Exception:
                            continue

                if browser:
                    browser.close()

                if _qr_state["status"] != "AUTHENTICATED":
                    _qr_state = {"status": "TIMEOUT", "image_base64": None, "message": "QR Code timed out. Click to try again."}

        except Exception as e:
            logger.error(f"Error during QR capture: {e}")
            _qr_state = {"status": "ERROR", "image_base64": None, "message": str(e)}
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass


def login_whatsapp_web(timeout_seconds: int = 90) -> Dict[str, Any]:
    """Starts the live QR capture thread."""
    global _qr_state
    if is_whatsapp_web_logged_in():
        return {"status": "AUTHENTICATED", "is_linked": True, "message": "WhatsApp Web is already linked!"}

    _qr_state = {"status": "LOADING", "image_base64": None, "message": "Opening WhatsApp Web and generating QR code..."}
    threading.Thread(target=start_live_qr_capture, args=(timeout_seconds,), daemon=True).start()
    return {"status": "started", "message": "Generating QR code..."}


def send_whatsapp_message_automated(phone: str, message: str, headless: bool = True) -> Dict[str, Any]:
    """
    Sends an automated WhatsApp message to a phone number using the persistent WhatsApp Web session.
    Used by the background follow-up scheduler on Day 3, 5, 7, 10 and Live Dispatch.
    """
    formatted_phone = format_whatsapp_phone(phone)
    if not formatted_phone:
        return {"status": "FAILED", "error": "Invalid phone number"}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "FAILED", "error": "Playwright is not installed"}

    encoded_text = urllib.parse.quote(message)
    target_url = f"https://web.whatsapp.com/send?phone={formatted_phone}&text={encoded_text}"

    with _browser_lock:
        logger.info(f"[AUTOMATED WA DISPATCH] Preparing message for +{formatted_phone}...")
        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=headless,
                    args=BROWSER_ARGS,
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800}
                )
                pages = browser.pages
                page = pages[0] if pages else browser.new_page()
                page.goto(target_url, timeout=45000, wait_until="domcontentloaded")

                start_time = time.time()
                send_success = False

                # Poll for up to 18 seconds for WhatsApp Web chat to load
                while time.time() - start_time < 18:
                    time.sleep(1.0)

                    # 1. Check if session was unlinked / showing QR code
                    if page.locator("canvas, div[data-ref]").count() > 0:
                        logger.warning("[AUTOMATED WA DISPATCH] WhatsApp Web session is expired or not authenticated.")
                        if SESSION_MARKER.exists():
                            SESSION_MARKER.unlink(missing_ok=True)
                        browser.close()
                        return {"status": "SESSION_EXPIRED", "error": "WhatsApp Web session expired or not authenticated."}

                    # 2. Check for invalid phone popup
                    invalid_dialog = page.locator("div[data-testid='popup-contents'], div[role='dialog']:has-text('invalid'), div[role='dialog']:has-text('Phone number shared')")
                    if invalid_dialog.count() > 0 and invalid_dialog.first.is_visible():
                        logger.warning(f"[AUTOMATED WA DISPATCH] Phone +{formatted_phone} is invalid or not on WhatsApp.")
                        browser.close()
                        return {"status": "FAILED", "error": "Phone number is not on WhatsApp"}

                    # 3. Check Send button
                    send_selectors = [
                        "button[aria-label='Send']",
                        "span[data-icon='send']",
                        "span[data-icon='send-light']",
                        "[data-testid='send']",
                        "[data-testid='compose-btn-send']",
                        "button:has(span[data-icon='send'])"
                    ]
                    for sel in send_selectors:
                        try:
                            btn = page.locator(sel)
                            if btn.count() > 0 and btn.first.is_visible():
                                btn.first.click()
                                send_success = True
                                logger.info(f"[AUTOMATED WA DISPATCH] Clicked Send button ({sel}) for +{formatted_phone}.")
                                break
                        except Exception:
                            continue

                    if send_success:
                        break

                    # 4. Fallback: Press Enter on the input box
                    try:
                        input_box = page.locator("footer div[contenteditable='true'], div[data-lexical-editor='true'], div[aria-label='Type a message'], div[contenteditable='true'][data-tab='10'], div[contenteditable='true']")
                        if input_box.count() > 0 and input_box.first.is_visible():
                            target_box = input_box.last
                            target_box.click()
                            target_box.press("Enter")
                            time.sleep(1.0)
                            send_success = True
                            logger.info(f"[AUTOMATED WA DISPATCH] Pressed Enter in message input for +{formatted_phone}.")
                            break
                    except Exception:
                        pass

                if send_success:
                    time.sleep(3.5)  # Wait for message to transmit
                    browser.close()
                    logger.info(f"✅ [AUTOMATED WA DISPATCH] Successfully delivered message to +{formatted_phone}")
                    return {"status": "SENT", "phone": formatted_phone, "delivered_at": time.time()}
                else:
                    browser.close()
                    logger.warning(f"⚠️ [AUTOMATED WA DISPATCH] Could not locate send button or input for +{formatted_phone}")
                    return {"status": "FAILED", "error": "Send button or chat box not found for this number"}

        except Exception as e:
            logger.error(f"❌ [AUTOMATED WA DISPATCH] Failed to send message to +{formatted_phone}: {e}")
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            return {"status": "FAILED", "error": str(e)}
