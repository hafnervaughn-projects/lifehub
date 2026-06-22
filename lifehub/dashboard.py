from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
from pathlib import Path

from .data_loader import MockDataLoader
from .hydration import HydrationStore
from .checklists import ChecklistStore
from .models import DashboardState
from .scheduler import (
    assignment_bucket,
    adaptive_routine_plan,
    build_timeline,
    build_alerts,
    calculate_wake_up_time,
    calculate_wind_down,
    calculate_sleep_plan,
    current_activity,
    detect_conflicts,
    next_item,
    next_school_work,
    next_shift,
    schedule_workout,
)


def build_dashboard(now: datetime | None = None, data_dir: Path | None = None, sync_manager=None) -> DashboardState:
    now = now or datetime.now()
    data_dir = data_dir or Path(__file__).resolve().parent.parent / "mock_data"
    loader = MockDataLoader(data_dir)
    events = loader.load_events(now)
    assignments = loader.load_assignments(now)
    workouts = loader.load_workouts()
    chores = loader.load_chores(now)
    hydration = HydrationStore(data_dir / "hydration_state.json").load(now)
    groceries = loader.load_groceries()
    checklist_state = ChecklistStore(data_dir / "checklist_state.json").load(now)

    today_name = now.strftime("%A")
    workout = next((item for item in workouts if item.weekday == today_name), None)
    workout = schedule_workout(now, workout, events)
    active_chores = []
    for chore in chores:
        if chore.completed:
            continue
        if chore.due_at and chore.due_at.date() == now.date() and chore.weekday in {None, "Daily", today_name}:
            active_chores.append(chore)
        elif chore.due_at is None and chore.weekday in {None, "Daily", today_name}:
            active_chores.append(chore)
    assignment_rows = [
        {
            "id": item.id,
            "title": item.title,
            "course": item.course,
            "due_at": item.due_at.isoformat(),
            "due_label": assignment_bucket(item.due_at, now),
        }
        for item in assignments
        if not item.submitted
    ]
    tomorrow_date = now.date() + timedelta(days=1)
    tomorrow_events = [event for event in events if event.start.date() == tomorrow_date]
    tomorrow_assignments = [
        item for item in assignments if not item.submitted and item.due_at.date() == tomorrow_date
    ]
    tomorrow_workout = next((item for item in workouts if item.weekday == tomorrow_date.strftime("%A")), None)
    sleep_plan = adaptive_routine_plan(now, events, tomorrow_workout)
    scheduled_tomorrow_workout = schedule_workout(sleep_plan["wake_up_time"], tomorrow_workout, events)
    conflicts = detect_conflicts(now, events, scheduled_tomorrow_workout, sleep_plan)
    timeline = build_timeline(now, events, workout, active_chores, sleep_plan)
    week_calendar = []
    for offset in range(7):
        day = now + timedelta(days=offset)
        day_date = day.date()
        day_workout = next((deepcopy(item) for item in workouts if item.weekday == day.strftime("%A")), None)
        day_workout = schedule_workout(datetime.combine(day_date, datetime.min.time()), day_workout, events)
        day_chores = [
            chore for chore in loader.load_chores(day)
            if chore.due_at and chore.due_at.date() == day_date
        ]
        items = [
            {
                "title": event.title,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "category": event.category,
            }
            for event in events if event.start.date() == day_date
        ]
        if day_workout and not day_workout.is_rest_day:
            workout_at = day_workout.recommended_start or datetime.combine(day_date, datetime.min.time()).replace(hour=10)
            items.append({
                "title": day_workout.name,
                "start": workout_at.isoformat(),
                "end": (workout_at + timedelta(minutes=day_workout.duration_minutes)).isoformat(),
                "category": "workout",
            })
        items += [
            {
                "title": chore.title,
                "start": chore.due_at.isoformat(),
                "end": (chore.due_at + timedelta(minutes=30)).isoformat(),
                "category": "chore",
            }
            for chore in day_chores
        ]
        items += [
            {
                "title": assignment.title,
                "start": assignment.due_at.isoformat(),
                "end": (assignment.due_at + timedelta(minutes=30)).isoformat(),
                "category": "assignment",
            }
            for assignment in assignments if not assignment.submitted and assignment.due_at.date() == day_date
        ]
        week_calendar.append({
            "date": day_date.isoformat(),
            "label": day.strftime("%a"),
            "is_today": offset == 0,
            "items": sorted(items, key=lambda item: item["start"]),
        })
    alerts = build_alerts(now, events, assignments, active_chores, workout)
    freshness = sync_manager.freshness(now) if sync_manager else {"overall": "fresh", "sources": {}}
    weather = sync_manager.weather() if sync_manager else None
    sync_status = "All sources current" if freshness["overall"] == "fresh" else "Some data is stale"
    needs_attention = (
        alerts and alerts[0].level.value in {"urgent", "critical"}
    ) or any(conflict["level"] in {"urgent", "critical"} for conflict in conflicts)
    day_status = "Attention needed" if needs_attention else "On track"
    return DashboardState(
        generated_at=now,
        sync_status=sync_status,
        sync_details=freshness,
        weather=weather,
        tomorrow={
            "date": tomorrow_date.isoformat(),
            "first_event": tomorrow_events[0].title if tomorrow_events else "No scheduled events",
            "event_count": len(tomorrow_events),
            "assignment_count": len(tomorrow_assignments),
            "workout": tomorrow_workout.name if tomorrow_workout else "No workout planned",
            "workout_time": (
                scheduled_tomorrow_workout.recommended_start.isoformat()
                if scheduled_tomorrow_workout and scheduled_tomorrow_workout.recommended_start
                else None
            ),
            "workout_note": sleep_plan["workout_note"],
            "wake_up_time": sleep_plan["wake_up_time"].isoformat(),
        },
        timeline=timeline,
        week_calendar=week_calendar,
        conflicts=conflicts,
        day_status=day_status,
        now=current_activity(now, events, workout),
        next=next_item(now, events, assignments),
        next_shift=next_shift(now, events),
        next_school_work=next_school_work(now, assignments),
        schedule=[event for event in events if event.end >= now][:5],
        workout=workout,
        assignments=assignment_rows,
        hydration=hydration,
        groceries=groceries[:6],
        chores=active_chores,
        wake_up_time=sleep_plan["wake_up_time"],
        wake_up_routine=["Stretch", "Rollout", "Shower", "Eat breakfast", "Hydration check"],
        alerts=alerts,
        wind_down_time=sleep_plan["wind_down_time"],
        bedtime=sleep_plan["bedtime"],
        sleep_note=sleep_plan["note"],
        checklist_state=checklist_state,
    )
