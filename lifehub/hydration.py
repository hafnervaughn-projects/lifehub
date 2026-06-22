from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

from .models import HydrationState


DEFAULT_GOAL = 5
DEFAULT_START = time(10, 0)
DEFAULT_END = time(23, 0)


class HydrationStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self, now: datetime) -> HydrationState:
        row = self._read()
        if row.get("date") != now.date().isoformat():
            row = self._new_day(now)
            self._write(row)
        return self._state(row, now)

    def add_bottle(self, now: datetime) -> HydrationState:
        row = self._read()
        if row.get("date") != now.date().isoformat():
            row = self._new_day(now)
        row["current_bottles"] = min(row["bottle_goal"], row["current_bottles"] + 1)
        row["last_updated"] = now.isoformat()
        self._write(row)
        return self._state(row, now)

    def reset(self, now: datetime) -> HydrationState:
        row = self._new_day(now)
        self._write(row)
        return self._state(row, now)

    def _state(self, row: dict, now: datetime) -> HydrationState:
        goal = row["bottle_goal"]
        count = row["current_bottles"]
        checkpoints = _checkpoints(now, goal)
        next_checkpoint = checkpoints[count] if count < goal else None
        expected = sum(checkpoint <= now for checkpoint in checkpoints)
        if count >= goal:
            status = "complete"
            message = "Daily hydration goal complete"
        elif count < expected:
            status = "behind"
            message = f"{expected - count} bottle{'s' if expected - count != 1 else ''} behind schedule"
        else:
            status = "on_track"
            message = "On track"
        return HydrationState(goal, count, next_checkpoint, status, message)

    def _new_day(self, now: datetime) -> dict:
        return {
            "date": now.date().isoformat(),
            "bottle_goal": DEFAULT_GOAL,
            "current_bottles": 0,
            "last_updated": now.isoformat(),
        }

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(row, indent=2), encoding="utf-8")


def _checkpoints(now: datetime, goal: int) -> list[datetime]:
    start = datetime.combine(now.date(), DEFAULT_START)
    end = datetime.combine(now.date(), DEFAULT_END)
    spacing = (end - start) / max(goal - 1, 1)
    return [start + spacing * index for index in range(goal)]
