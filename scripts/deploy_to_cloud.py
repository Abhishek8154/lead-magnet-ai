import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 1. Export static demos to public_demos
from demo.export_static_demos import export_all_static_demos
export_all_static_demos(PROJECT_ROOT / "public_demos")

# 2. Deploy public_demos to Surge
domain = "leadmagnet-demos.surge.sh"
print(f"\nDeploying {PROJECT_ROOT / 'public_demos'} to https://{domain} ...")

res = subprocess.run(
    f'npx --yes surge "{PROJECT_ROOT / "public_demos"}" {domain}',
    shell=True,
    capture_output=True,
    text=True
)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
print("EXIT CODE:", res.returncode)
