from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AlertLevel(str, Enum):
    NORMAL = "normal"
    SOON = "soon"
    URGENT = "urgent"
    CRITICAL = "critical"


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    category: str
    location: str = ""
    source: str = "mock"
    important: bool = True


@dataclass
class Assignment:
    id: str
    title: str
    course: str
    due_at: datetime
    source_url: str = ""
    submitted: bool = False


@dataclass
class WorkoutSection:
    name: str
    items: list[str]
    cue: str = ""


@dataclass
class Workout:
    id: str
    name: str
    weekday: str
    duration_minutes: int
    includes_lifting: bool
    details: list[str] = field(default_factory=list)
    sections: list[WorkoutSection] = field(default_factory=list)
    intensity: str = ""
    is_rest_day: bool = False
    backup_plan_template: str = ""
    recommended_start: datetime | None = None
    backup_plan: str = ""


@dataclass
class Chore:
    id: str
    title: str
    weekday: str | None = None
    due_at: datetime | None = None
    completed: bool = False


@dataclass
class HydrationState:
    bottle_goal: int
    current_bottles: int
    next_checkpoint: datetime | None
    status: str = "on_track"
    message: str = ""


@dataclass
class GroceryItem:
    id: str
    name: str
    quantity: str = "1"
    checked: bool = False


@dataclass
class Alert:
    id: str
    message: str
    level: AlertLevel
    due_at: datetime | None = None
    action: str = ""


@dataclass
class DashboardState:
    generated_at: datetime
    sync_status: str
    sync_details: dict[str, Any]
    weather: dict[str, Any] | None
    tomorrow: dict[str, Any]
    timeline: list[dict[str, Any]]
    week_calendar: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    day_status: str
    now: dict[str, Any]
    next: dict[str, Any] | None
    next_shift: dict[str, Any] | None
    next_school_work: dict[str, Any] | None
    schedule: list[CalendarEvent]
    workout: Workout | None
    assignments: list[dict[str, Any]]
    hydration: HydrationState
    groceries: list[GroceryItem]
    chores: list[Chore]
    wake_up_time: datetime
    wake_up_routine: list[str]
    alerts: list[Alert]
    wind_down_time: datetime
    bedtime: datetime
    sleep_note: str
    checklist_state: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value
