from __future__ import annotations

import re
from datetime import datetime, timedelta


def parse_work_ical(text: str, source: str = "schedulefly-ical") -> list[dict]:
    events = []
    current: dict[str, str] | None = None
    for line in _unfold_lines(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            row = _event_to_work_row(current, source)
            if row:
                events.append(row)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0]] = _unescape(value)
    return sorted(events, key=lambda item: (item["date"], item["start_time"]))


def _event_to_work_row(event: dict[str, str], source: str) -> dict | None:
    title = event.get("SUMMARY", "Work shift").strip()
    start_raw = event.get("DTSTART")
    if not start_raw:
        return None
    start = _parse_ical_datetime(start_raw)
    end = _parse_ical_datetime(event["DTEND"]) if event.get("DTEND") else start + timedelta(hours=4)
    location = event.get("LOCATION", "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", f"{start.date()}-{title}-{location}".lower()).strip("-")
    return {
        "id": f"schedulefly-{slug}",
        "title": title if title.lower().startswith("work") else f"Work: {title}",
        "date": start.date().isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "category": "work",
        "location": location,
        "source": source,
    }


def _parse_ical_datetime(value: str) -> datetime:
    value = value.rstrip("Z")
    for pattern in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"Unsupported iCal date: {value}")


def _unfold_lines(text: str) -> list[str]:
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _unescape(value: str) -> str:
    return value.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
