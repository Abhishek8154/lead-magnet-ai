import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import Database
import httpx

db = Database()
leads = db.get_all_leads()
print(f"Testing {len(leads)} leads demo URLs...")
failed_urls = []
for l in leads:
    url = l.demo_url
    try:
        r = httpx.get(url, timeout=6.0, follow_redirects=True)
        status = r.status_code
        if status != 200:
            failed_urls.append((l.business_name, url, status))
    except Exception as e:
        status = f"ERR: {e}"
        failed_urls.append((l.business_name, url, status))
    print(f"{l.business_name[:35]}: {url} -> {status}")

print("\n--- SUMMARY ---")
print(f"Total: {len(leads)}, Failed: {len(failed_urls)}")
for f in failed_urls:
    print(f"  FAILED: {f[0]} | {f[1]} -> {f[2]}")
