from __future__ import annotations

import re
from datetime import datetime


def parse_canvas_ical(text: str) -> list[dict]:
    """Normalize Canvas VEVENT entries into LifeHub assignment snapshot rows."""
    lines = _unfold_lines(text)
    events = []
    current: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            row = _event_to_assignment(current)
            if row:
                events.append(row)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0]] = _unescape(value)
    return sorted(events, key=lambda item: item["due_at"])


def _unfold_lines(text: str) -> list[str]:
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _event_to_assignment(event: dict[str, str]) -> dict | None:
    due_at = event.get("DTSTART")
    title = event.get("SUMMARY")
    if not due_at or not title:
        return None
    course_match = re.search(r"\[(.+?)\]\s*$", title)
    course = course_match.group(1) if course_match else "Canvas"
    clean_title = re.sub(r"\s*\[.+?\]\s*$", "", title)
    return {
        "id": event.get("UID", f"canvas-{due_at}-{clean_title}"),
        "title": clean_title,
        "course": course,
        "due_at": _parse_ical_datetime(due_at).isoformat(),
        "source_url": event.get("URL", ""),
        "submitted": False,
    }


def _parse_ical_datetime(value: str) -> datetime:
    value = value.rstrip("Z")
    for pattern in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"Unsupported iCal date: {value}")


def _unescape(value: str) -> str:
    return value.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
