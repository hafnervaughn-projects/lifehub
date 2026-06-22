import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifehub.canvas_ical import parse_canvas_ical


parser = argparse.ArgumentParser(description="Refresh LifeHub's Canvas iCal snapshot.")
parser.add_argument("--file", type=Path, help="Read a previously downloaded .ics file.")
args = parser.parse_args()

if args.file:
    text = args.file.read_text(encoding="utf-8")
else:
    url = os.environ.get("CANVAS_ICAL_URL")
    if not url:
        raise SystemExit("Set CANVAS_ICAL_URL or provide --file.")
    with urlopen(url, timeout=20) as response:
        text = response.read().decode("utf-8")

assignments = parse_canvas_ical(text)
output = Path(__file__).resolve().parent.parent / "mock_data" / "canvas_assignments.json"
output.write_text(json.dumps(assignments, indent=2), encoding="utf-8")
print(f"Imported {len(assignments)} Canvas calendar items.")
