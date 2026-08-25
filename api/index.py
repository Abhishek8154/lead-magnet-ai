import sys
import os
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Flag as Vercel serverless environment
os.environ["VERCEL_ENV"] = "true"

try:
    from web.app import app
except Exception as err:
    import traceback
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    
    app = FastAPI(title="Lead Magnet AI Error Handler")
    tb = traceback.format_exc()

    @app.get("/{full_path:path}")
    def error_fallback(full_path: str):
        return HTMLResponse(content=f"""
        <div style="font-family: monospace; padding: 2rem; background: #0f172a; color: #f87171; border-radius: 12px; margin: 2rem auto; max-width: 800px;">
            <h2>⚠️ Serverless Module Import Error</h2>
            <p><strong>Error:</strong> {err}</p>
            <pre style="background: #1e293b; padding: 1rem; border-radius: 8px; color: #e2e8f0; overflow: auto;">{tb}</pre>
        </div>
        """, status_code=500)
