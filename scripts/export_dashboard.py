import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifehub.dashboard import build_dashboard


output = Path("examples/dashboard.json")
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(build_dashboard().to_dict(), indent=2), encoding="utf-8")
print(f"Wrote {output}")
