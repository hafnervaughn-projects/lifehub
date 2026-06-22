from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

from .models import Assignment, CalendarEvent, Chore, GroceryItem, Workout, WorkoutSection


class MockDataLoader:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def _read(self, filename: str):
        return json.loads((self.data_dir / filename).read_text(encoding="utf-8"))

    def load_events(self, now: datetime) -> list[CalendarEvent]:
        events = []
        for row in self._read("work_schedule.json"):
            day = (
                datetime.fromisoformat(row["date"]).date()
                if row.get("date")
                else now.date() + timedelta(days=row["day_offset"])
            )
            start = datetime.combine(day, time.fromisoformat(row["start_time"]))
            end = datetime.combine(day, time.fromisoformat(row["end_time"]))
            if end <= start:
                end += timedelta(days=1)
            events.append(
                CalendarEvent(
                    id=row["id"],
                    title=row["title"],
                    start=start,
                    end=end,
                    category=row["category"],
                    location=row.get("location", ""),
                    source=row.get("source", "mock"),
                )
            )
        return sorted(events, key=lambda event: event.start)

    def load_assignments(self, now: datetime) -> list[Assignment]:
        assignments = []
        for row in self._read("canvas_assignments.json"):
            due_at = (
                datetime.fromisoformat(row["due_at"])
                if row.get("due_at")
                else datetime.combine(
                    now.date() + timedelta(days=row["due_day_offset"]),
                    time.fromisoformat(row["due_time"]),
                )
            )
            assignments.append(
                Assignment(
                    id=row["id"],
                    title=row["title"],
                    course=row["course"],
                    due_at=due_at,
                    source_url=row.get("source_url", ""),
                    submitted=row.get("submitted", False),
                )
            )
        return sorted(assignments, key=lambda assignment: assignment.due_at)

    def load_workouts(self) -> list[Workout]:
        workouts = []
        for raw_row in self._read("workouts.json"):
            row = dict(raw_row)
            sections = [WorkoutSection(**section) for section in row.pop("sections", [])]
            workouts.append(Workout(**row, sections=sections))
        return workouts

    def load_chores(self, now: datetime) -> list[Chore]:
        chores = []
        for row in self._read("chores.json"):
            due_at = None
            weekday = row.get("weekday")
            if weekday == "Daily" or weekday == now.strftime("%A"):
                due_at = datetime.combine(now.date(), time.fromisoformat(row["due_time"]))
            elif row.get("due_day_offset") is not None:
                due_day = now.date() + timedelta(days=row["due_day_offset"])
                due_at = datetime.combine(due_day, time.fromisoformat(row["due_time"]))
            chores.append(
                Chore(
                    id=row["id"],
                    title=row["title"],
                    weekday=weekday,
                    due_at=due_at,
                    completed=row.get("completed", False),
                )
            )
        return chores

    def load_groceries(self) -> list[GroceryItem]:
        return [GroceryItem(**row) for row in self._read("groceries.json")]
