from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class ChecklistStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self, now: datetime) -> dict:
        state = self._read()
        if state.get("date") != now.date().isoformat():
            state = {"date": now.date().isoformat(), "chores": [], "groceries": [], "wake_up": []}
            self._write(state)
        return state

    def toggle(self, group: str, item_id: str, now: datetime) -> dict:
        state = self.load(now)
        completed = set(state.get(group, []))
        completed.remove(item_id) if item_id in completed else completed.add(item_id)
        state[group] = sorted(completed)
        self._write(state)
        return state

    def set_group(self, group: str, item_ids: list[str], complete: bool, now: datetime) -> dict:
        state = self.load(now)
        state[group] = sorted(item_ids) if complete else []
        self._write(state)
        return state

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")
