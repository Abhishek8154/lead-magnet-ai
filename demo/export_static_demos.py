import sys
import json
import shutil
from typing import Optional
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader
from database import Database
from demo.server import generate_slug
from config import config
from utils.logger import get_logger

logger = get_logger("StaticDemoExporter")


def export_all_static_demos(output_dir: Optional[Path] = None):
    """
    Renders all leads from SQLite database into standalone, static HTML files.
    Outputs to output_dir (default: PROJECT_ROOT / 'public_demos').
    Can be hosted on GitHub Pages, Vercel, Netlify, Cloudflare Pages, or any static host 24/7.
    """
    if output_dir is None:
        output_dir = PROJECT_ROOT / "public_demos"

    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = output_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    db = Database()
    db.init_db()
    all_leads = db.get_all_leads()

    templates_dir = PROJECT_ROOT / "demo" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("preview.html")

    exported_count = 0
    exported_slugs = []

    for lead in all_leads:
        slug = generate_slug(lead.business_name, lead.city)
        
        # Parse rating from raw_data if available
        rating = None
        if lead.raw_data:
            try:
                raw_meta = json.loads(lead.raw_data)
                rating = raw_meta.get("rating")
            except (json.JSONDecodeError, TypeError):
                pass

        lead_dict = lead.to_dict()
        lead_dict["rating"] = rating

        # Render HTML string
        html_content = template.render(request=None, lead=lead_dict)

        # 1. Save to preview/{slug}.html
        slug_file = preview_dir / f"{slug}.html"
        slug_file.write_text(html_content, encoding="utf-8")

        # 2. Save to preview/{slug}/index.html for clean directory routing
        slug_folder = preview_dir / slug
        slug_folder.mkdir(parents=True, exist_ok=True)
        (slug_folder / "index.html").write_text(html_content, encoding="utf-8")

        exported_count += 1
        exported_slugs.append(slug)
        logger.info(f"[{exported_count}/{len(all_leads)}] Exported static preview for '{lead.business_name}' -> preview/{slug}/index.html")

    print("\n" + "=" * 70)
    print(f"🎉 EXPORTED {exported_count} STATIC DEMO PAGES TO: {output_dir}")
    print("👉 These static HTML files can be hosted on GitHub Pages, Vercel, or Netlify")
    print("   to stay online 24/7 even when your system is powered off!")
    print("=" * 70 + "\n")

    return exported_count


def export_and_publish_demos_to_github(leads: Optional[List[Lead]] = None):
    """
    Renders static demo HTML files to both docs/ and public/ directories,
    and automatically pushes them to GitHub in the background so they are
    instantly live on GitHub Pages 24/7.
    """
    import subprocess
    import threading

    docs_dir = PROJECT_ROOT / "docs"
    public_dir = PROJECT_ROOT / "public"
    public_demos_dir = PROJECT_ROOT / "public_demos"

    export_all_static_demos(docs_dir)
    export_all_static_demos(public_dir)
    export_all_static_demos(public_demos_dir)

    def _bg_push():
        try:
            logger.info("Auto-syncing newly generated client demo pages to GitHub...")
            subprocess.run(["git", "add", "docs", "public", "public_demos"], cwd=str(PROJECT_ROOT), check=True, capture_output=True)
            commit_res = subprocess.run(["git", "commit", "-m", "Auto-publish new client demo websites to GitHub Pages"], cwd=str(PROJECT_ROOT), capture_output=True)
            if commit_res.returncode == 0:
                push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, timeout=60)
                if push_res.returncode == 0:
                    logger.info("Successfully published new client demo websites to GitHub Pages 24/7!")
                else:
                    logger.warning(f"Git push warning: {push_res.stderr.decode('utf-8', errors='ignore')}")
            else:
                logger.info("No new demo file changes to commit.")
        except Exception as err:
            logger.warning(f"Background GitHub auto-publish error: {err}")

    t = threading.Thread(target=_bg_push, daemon=True)
    t.start()


if __name__ == "__main__":
    export_all_static_demos()

