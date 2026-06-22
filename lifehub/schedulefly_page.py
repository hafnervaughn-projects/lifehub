from __future__ import annotations

import re
from datetime import date, datetime, timedelta


TIME_RE = re.compile(r"(\d{1,2}:\d{2})(AM|PM)\s*-\s*(\d{1,2}:\d{2})(AM|PM)", re.I)
DATE_RE = re.compile(r"\b(?:Mon|Tue|Tues|Wed|Thu|Thur|Fri|Sat|Sun)[a-z]*\s+([A-Za-z]{3,9})\s+(\d{1,2})\b", re.I)


def parse_schedulefly_rows(
    rows: list[list[str]],
    employee_name: str = "Hafner, Vaughn",
    today: date | None = None,
) -> list[dict]:
    """Convert Schedulefly table rows from the signed-in schedule page into work shifts."""
    today = today or datetime.now().date()
    current_dates: list[date] = []
    shifts: list[dict] = []
    for row in rows:
        if len(row) >= 2 and row[0] == "Employee":
            current_dates = _header_dates(row[1:], today)
            continue
        if row and _name_matches(row[0], employee_name) and current_dates:
            for index, cell in enumerate(row[1:]):
                if index >= len(current_dates):
                    break
                shifts.extend(_cell_to_shifts(cell, current_dates[index]))
    return shifts


def parse_personal_schedulefly_rows(rows: list[list[str]], today: date | None = None) -> list[dict]:
    """Parse the 7-column personal schedule table from Schedulefly's home page."""
    today = today or datetime.now().date()
    dates: list[date] = []
    shifts: list[dict] = []
    for row in rows:
        parsed_dates = _header_dates(row, today)
        if len(parsed_dates) >= 3:
            dates = parsed_dates
            continue
        if dates:
            for index, cell in enumerate(row):
                if index >= len(dates):
                    break
                shifts.extend(_cell_to_shifts(cell, dates[index]))
    return _dedupe(shifts)


def parse_schedulefly_text(
    text: str,
    employee_name: str = "Hafner, Vaughn",
    today: date | None = None,
) -> list[dict]:
    """Fallback parser for Schedulefly pages where table rows are hard to inspect."""
    today = today or datetime.now().date()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headers = _week_dates_from_text(text, today)
    for line_index, line in enumerate(lines):
        if line.startswith("Employee\t") and "Today" in line:
            parsed_headers = _header_dates(line.split("\t")[1:], today)
            headers = parsed_headers if len(parsed_headers) >= 3 else headers
            continue
        if headers and "\t" in line and _name_matches(line.split("\t", 1)[0], employee_name):
            row_lines = [line]
            for next_line in lines[line_index + 1:]:
                if re.match(r"^[A-Z][A-Za-z' -]+,\s+[A-Z][^\t]*\t", next_line):
                    break
                if next_line in {"Host", "Server", "Support", "Bar", "Expo", "FOH Manager", "Manager", "Kitchen"}:
                    break
                row_lines.append(next_line)
            cells = "\n".join(row_lines).split("\t")
            return [
                shift
                for index, cell in enumerate(cells[1:])
                if index < len(headers)
                for shift in _cell_to_shifts(cell, headers[index])
            ]
    return []


def parse_personal_schedulefly_text(text: str, today: date | None = None) -> list[dict]:
    """Parse the simpler personal schedule block from Schedulefly's home page."""
    today = today or datetime.now().date()
    lines = [line.strip() for line in text.splitlines() if line.strip() and "Giveup Shift" not in line]
    shifts: list[dict] = []
    current_date: date | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        date_match = DATE_RE.search(line)
        if line.lower() == "today":
            current_date = today
        elif date_match:
            month = datetime.strptime(date_match.group(1)[:3], "%b").month
            year = today.year + (1 if month < today.month - 6 else 0)
            current_date = date(year, month, int(date_match.group(2)))
        time_match = TIME_RE.search(line)
        if current_date and time_match:
            cell_lines = [line[time_match.start():]]
            index += 1
            while index < len(lines) and not DATE_RE.search(lines[index]) and not TIME_RE.search(lines[index]):
                if lines[index].lower() not in {"my schedule", "schedule", "upcoming shifts"}:
                    cell_lines.append(lines[index])
                index += 1
            shifts.extend(_cell_to_shifts("\n".join(cell_lines), current_date))
            continue
        index += 1
    return _dedupe(shifts or _parse_near_name(lines, today))


def _parse_near_name(lines: list[str], today: date) -> list[dict]:
    shifts: list[dict] = []
    for index, line in enumerate(lines):
        if "vaughn" not in line.lower():
            continue
        window = lines[max(0, index - 8): index + 35]
        current_date: date | None = None
        for item in window:
            date_match = DATE_RE.search(item)
            if item.lower() == "today":
                current_date = today
            elif date_match:
                month = datetime.strptime(date_match.group(1)[:3], "%b").month
                year = today.year + (1 if month < today.month - 6 else 0)
                current_date = date(year, month, int(date_match.group(2)))
            if current_date and TIME_RE.search(item):
                shifts.extend(_cell_to_shifts(item, current_date))
    return shifts


def _week_dates_from_text(text: str, today: date) -> list[date]:
    match = re.search(r"Schedules for\s+([A-Za-z]{3,9})\s+(\d{1,2})\s+-\s+([A-Za-z]{3,9})?\s*(\d{1,2})", text)
    if match:
        start_month, start_day = match.group(1), int(match.group(2))
        month = datetime.strptime(start_month[:3], "%b").month
        year = today.year + (1 if month < today.month - 6 else 0)
        start = date(year, month, start_day)
        return [start + timedelta(days=offset) for offset in range(7)]
    return [today + timedelta(days=offset) for offset in range(7)]


def _header_dates(labels: list[str], today: date) -> list[date]:
    dates = []
    for label in labels:
        text = " ".join(label.split())
        if text == "Today":
            dates.append(today)
            continue
        match = re.search(r"([A-Za-z]+)\s+([A-Za-z]{3,9})\s+(\d{1,2})", text)
        if not match:
            match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})", text)
        if match:
            month_name, day_number = match.groups()[-2:]
            try:
                month = datetime.strptime(month_name[:3], "%b").month
            except ValueError:
                continue
            year = today.year + (1 if month < today.month - 6 else 0)
            dates.append(date(year, month, int(day_number)))
    return dates


def _cell_to_shifts(cell: str, shift_date: date) -> list[dict]:
    lines = [
        line.strip()
        for line in cell.splitlines()
        if line.strip()
        and "Giveup" not in line
        and not (line.strip().startswith("(") and line.strip().endswith(")"))
        and line.strip().lower() not in {"lunch", "dinner"}
    ]
    shifts = []
    index = 0
    while index < len(lines):
        match = TIME_RE.search(lines[index])
        if not match:
            index += 1
            continue
        start_time, start_ampm, end_time, end_ampm = match.groups()
        location_parts = [lines[index][match.end():].strip()]
        location_parts = [part for part in location_parts if part]
        index += 1
        while index < len(lines) and not TIME_RE.search(lines[index]):
            location_parts.append(lines[index])
            index += 1
        start = _to_24_hour(start_time, start_ampm)
        end = _to_24_hour(end_time, end_ampm)
        location = " / ".join(location_parts).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", f"{shift_date}-{start}-{location}".lower()).strip("-")
        shifts.append(
            {
                "id": f"schedulefly-{slug}",
                "title": f"Work: {location or 'Shift'}",
                "date": shift_date.isoformat(),
                "start_time": start,
                "end_time": end,
                "category": "work",
                "location": location,
                "source": "schedulefly-browser",
            }
        )
    return shifts


def _to_24_hour(value: str, ampm: str) -> str:
    parsed = datetime.strptime(f"{value}{ampm.upper()}", "%I:%M%p")
    return parsed.strftime("%H:%M")


def _dedupe(shifts: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for shift in shifts:
        key = (shift["date"], shift["start_time"], shift["end_time"], shift["location"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(shift)
    return unique


def _name_matches(candidate: str, employee_name: str) -> bool:
    candidate_words = set(re.findall(r"[a-z]+", candidate.lower()))
    target_words = set(re.findall(r"[a-z]+", employee_name.lower()))
    if not candidate_words or not target_words:
        return False
    if candidate.strip().lower() == employee_name.strip().lower():
        return True
    return bool(candidate_words & target_words)
