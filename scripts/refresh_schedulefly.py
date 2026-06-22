from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lifehub.calendar_ical import parse_work_ical


def main() -> int:
    data_dir = ROOT / "mock_data"
    config_path = data_dir / "lifehub_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    url = os.environ.get("SCHEDULEFLY_ICAL_URL") or config.get("schedulefly_ical_url", "")
    if not url:
        print("No Schedulefly calendar URL configured.")
        print("Set SCHEDULEFLY_ICAL_URL or mock_data/lifehub_config.json -> schedulefly_ical_url.")
        return 1
    request = Request(url, headers={"User-Agent": "LifeHub/1.0"})
    with urlopen(request, timeout=20) as response:
        rows = parse_work_ical(response.read().decode("utf-8"))
    output = data_dir / "work_schedule.json"
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Updated {output} with {len(rows)} Schedulefly shifts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
