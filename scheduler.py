from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import Alert, AlertLevel, Assignment, CalendarEvent, Chore, Workout


GYM_OPEN = time(5, 0)
GYM_CLOSE = time(12, 0)
LIFT_TARGET_LATEST = time(11, 15)
DESIRED_SLEEP_HOURS = 8.75
MIN_SLEEP_HOURS = 8.5
WORKOUT_WAKE_BUFFER_MINUTES = 60


def current_activity(now: datetime, events: list[CalendarEvent], workout: Workout | None) -> dict:
    for event in events:
        if event.start <= now < event.end:
            return {"title": event.title, "type": event.category, "until": event.end.isoformat()}
    if workout and workout.recommended_start:
        end = workout.recommended_start + timedelta(minutes=workout.duration_minutes)
        if workout.recommended_start <= now < end:
            return {"title": workout.name, "type": "workout", "until": end.isoformat()}
    return {"title": "Open focus block", "type": "focus", "until": None}


def next_item(now: datetime, events: list[CalendarEvent], assignments: list[Assignment]) -> dict | None:
    candidates = [
        {"title": event.title, "type": event.category, "at": event.start}
        for event in events
        if event.start > now
    ]
    candidates += [
        {"title": assignment.title, "type": "assignment", "at": assignment.due_at}
        for assignment in assignments
        if not assignment.submitted and assignment.due_at > now
    ]
    if not candidates:
        return None
    result = min(candidates, key=lambda item: item["at"])
    result["at"] = result["at"].isoformat()
    return result


def next_shift(now: datetime, events: list[CalendarEvent]) -> dict | None:
    shifts = [event for event in events if event.category == "work" and event.start > now]
    if not shifts:
        return None
    shift = min(shifts, key=lambda event: event.start)
    return {
        "title": shift.title,
        "at": shift.start.isoformat(),
        "end": shift.end.isoformat(),
        "location": shift.location,
    }


def next_school_work(now: datetime, assignments: list[Assignment]) -> dict | None:
    upcoming = [
        assignment for assignment in assignments
        if not assignment.submitted and assignment.due_at > now
    ]
    if not upcoming:
        return None
    assignment = min(upcoming, key=lambda item: item.due_at)
    return {
        "title": assignment.title,
        "course": assignment.course,
        "at": assignment.due_at.isoformat(),
        "due_label": assignment_bucket(assignment.due_at, now),
    }


def schedule_workout(now: datetime, workout: Workout | None, events: list[CalendarEvent]) -> Workout | None:
    if workout is None:
        return None
    if workout.is_rest_day:
        return workout
    day_start = datetime.combine(now.date(), GYM_OPEN)
    latest_start_time = LIFT_TARGET_LATEST if workout.includes_lifting else time(11, 30)
    latest_start = datetime.combine(now.date(), latest_start_time)
    duration = timedelta(minutes=workout.duration_minutes)
    preferred_start = min(
        datetime.combine(now.date(), time(10, 0)),
        datetime.combine(now.date(), GYM_CLOSE) - duration,
    )
    cursor = max(now.replace(second=0, microsecond=0), day_start, preferred_start)

    busy = sorted(
        [(event.start, event.end) for event in events if event.start.date() == now.date()],
        key=lambda block: block[0],
    )
    while cursor <= latest_start:
        end = cursor + duration
        conflict = next((block for block in busy if cursor < block[1] and end > block[0]), None)
        if conflict is None and end <= datetime.combine(now.date(), GYM_CLOSE):
            workout.recommended_start = cursor
            return workout
        cursor = conflict[1] + timedelta(minutes=15) if conflict else cursor + timedelta(minutes=15)

    workout.backup_plan = workout.backup_plan_template or (
        "30-minute home strength circuit after the final event"
        if workout.includes_lifting
        else "25-minute easy run or mobility session after the final event"
    )
    return workout


def adaptive_routine_plan(
    now: datetime,
    events: list[CalendarEvent],
    tomorrow_workout: Workout | None,
    desired_sleep_hours: float = DESIRED_SLEEP_HOURS,
    wake_routine_minutes: int = 60,
) -> dict:
    """Protect sleep while reserving a valid pre-close window for tomorrow's lift."""
    plan = calculate_sleep_plan(now, events, desired_sleep_hours, wake_routine_minutes)
    tomorrow = now.date() + timedelta(days=1)
    if not tomorrow_workout or tomorrow_workout.is_rest_day:
        plan["workout_note"] = "Routine adjusts automatically when tomorrow's schedule changes"
        return plan

    duration = timedelta(minutes=tomorrow_workout.duration_minutes)
    close = datetime.combine(tomorrow, GYM_CLOSE)
    target_latest = datetime.combine(tomorrow, LIFT_TARGET_LATEST)
    latest_start = min(target_latest, close - duration)
    planned_workout = schedule_workout(datetime.combine(tomorrow, time(0, 0)), tomorrow_workout, events)
    if planned_workout and planned_workout.recommended_start:
        workout_start = planned_workout.recommended_start
    elif tomorrow_workout.includes_lifting:
        workout_start = latest_start
    else:
        workout_start = min(datetime.combine(tomorrow, time(10, 0)), close - duration)
    latest_wake = workout_start - timedelta(minutes=WORKOUT_WAKE_BUFFER_MINUTES)

    if plan["wake_up_time"] > latest_wake:
        plan["wake_up_time"] = latest_wake
        plan["bedtime"] = latest_wake - timedelta(hours=desired_sleep_hours)
        plan["wind_down_time"] = plan["bedtime"] - timedelta(minutes=45)

    earliest_possible_bedtime = _earliest_possible_bedtime(now, events)
    if plan["bedtime"] < earliest_possible_bedtime:
        plan["bedtime"] = earliest_possible_bedtime
        plan["wind_down_time"] = plan["bedtime"] - timedelta(minutes=45)
        plan["sleep_hours"] = (plan["wake_up_time"] - plan["bedtime"]).total_seconds() / 3600
        plan["workout_note"] = "Lift remains before noon; sleep and workout need a manual decision"
    else:
        plan["sleep_hours"] = desired_sleep_hours
        workout_time = workout_start.strftime("%I:%M %p").lstrip("0")
        if tomorrow_workout.includes_lifting:
            plan["workout_note"] = f"Wake time reserves a {workout_time} lift start before gym close"
        else:
            plan["workout_note"] = f"Wake time is at least 1 hour before the {workout_time} workout"
    plan["note"] = (
        f"Adaptive plan targets {plan['sleep_hours']:.1f} hours and protects tomorrow's lift"
        if tomorrow_workout.includes_lifting
        else f"Adaptive plan targets {plan['sleep_hours']:.1f} hours and keeps a 1-hour workout buffer"
    )
    return plan


def detect_conflicts(
    now: datetime,
    events: list[CalendarEvent],
    workout: Workout | None,
    sleep_plan: dict,
) -> list[dict]:
    conflicts = []
    relevant = sorted([event for event in events if event.end >= now], key=lambda event: event.start)
    for left, right in zip(relevant, relevant[1:]):
        if right.start < left.end:
            conflicts.append({
                "id": f"overlap-{left.id}-{right.id}",
                "level": "critical",
                "title": "Schedule overlap",
                "detail": f"{left.title} overlaps {right.title}",
                "suggestion": "Review which commitment should take priority",
            })
        elif right.start - left.end < timedelta(minutes=30) and left.end.date() == right.start.date():
            conflicts.append({
                "id": f"tight-{left.id}-{right.id}",
                "level": "soon",
                "title": "Tight transition",
                "detail": f"Only {int((right.start-left.end).total_seconds()/60)} minutes between {left.title} and {right.title}",
                "suggestion": "Prepare before the first event ends",
            })
    if workout and workout.includes_lifting and not workout.is_rest_day and not workout.recommended_start:
        conflicts.append({
            "id": "lift-window",
            "level": "urgent",
            "title": "No valid lift window",
            "detail": "The planned lift cannot finish before the gym closes at noon",
            "suggestion": workout.backup_plan or "Use the planned non-gym backup",
        })
    if sleep_plan.get("sleep_hours", DESIRED_SLEEP_HOURS) < MIN_SLEEP_HOURS:
        conflicts.append({
            "id": "sleep-shortfall",
            "level": "urgent",
            "title": "Sleep and schedule conflict",
            "detail": f"Current commitments allow only {sleep_plan['sleep_hours']:.1f} hours before the planned wake time",
            "suggestion": "Keep the lift before noon, shorten the workout, or adjust a commitment",
        })
    return conflicts


def build_timeline(
    now: datetime,
    events: list[CalendarEvent],
    workout: Workout | None,
    chores: list[Chore],
    sleep_plan: dict,
) -> list[dict]:
    end_of_day = datetime.combine(now.date() + timedelta(days=1), time(3, 0))
    items = [
        {
            "id": event.id,
            "title": event.title,
            "start": event.start.isoformat(),
            "end": event.end.isoformat(),
            "category": event.category,
        }
        for event in events
        if event.start.date() == now.date() and event.start < end_of_day
    ]
    if workout and not workout.is_rest_day:
        planned_start = workout.recommended_start or max(
            datetime.combine(now.date(), GYM_OPEN),
            min(
                datetime.combine(now.date(), time(10, 0)),
                datetime.combine(now.date(), GYM_CLOSE) - timedelta(minutes=workout.duration_minutes),
            ),
        )
        items.append({
            "id": workout.id,
            "title": workout.name if workout.recommended_start else f"{workout.name} (planned)",
            "start": planned_start.isoformat(),
            "end": (planned_start + timedelta(minutes=workout.duration_minutes)).isoformat(),
            "category": "workout",
        })
    for chore in chores:
        if chore.due_at:
            items.append({
                "id": chore.id,
                "title": chore.title,
                "start": chore.due_at.isoformat(),
                "end": (chore.due_at + timedelta(minutes=30)).isoformat(),
                "category": "chore",
            })
    for key, title, duration in (
        ("wind_down_time", "Wind-down", 45),
        ("bedtime", "Sleep", 0),
    ):
        start = sleep_plan[key]
        items.append({
            "id": key,
            "title": title,
            "start": start.isoformat(),
            "end": (sleep_plan["wake_up_time"] if key == "bedtime" else start + timedelta(minutes=duration)).isoformat(),
            "category": "sleep",
        })
    return sorted(items, key=lambda item: item["start"])


def assignment_bucket(due_at: datetime, now: datetime) -> str:
    days = (due_at.date() - now.date()).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "due today"
    if days == 1:
        return "due tomorrow"
    if days <= 7:
        return "due this week"
    return "later"


def calculate_wind_down(
    now: datetime,
    tomorrow_events: list[CalendarEvent],
    desired_sleep_hours: float = 8.75,
    wake_routine_minutes: int = 60,
    wind_down_minutes: int = 45,
    morning_workout_minutes: int = 0,
) -> datetime:
    return calculate_sleep_plan(
        now,
        tomorrow_events,
        desired_sleep_hours,
        wake_routine_minutes,
        wind_down_minutes,
        morning_workout_minutes,
    )["wind_down_time"]


def calculate_wake_up_time(
    now: datetime,
    tomorrow_events: list[CalendarEvent],
    wake_routine_minutes: int = 60,
    morning_workout_minutes: int = 0,
) -> datetime:
    return calculate_sleep_plan(
        now,
        tomorrow_events,
        wake_routine_minutes=wake_routine_minutes,
        morning_workout_minutes=morning_workout_minutes,
    )["wake_up_time"]


def calculate_sleep_plan(
    now: datetime,
    events: list[CalendarEvent],
    desired_sleep_hours: float = 8.75,
    wake_routine_minutes: int = 60,
    wind_down_minutes: int = 45,
    morning_workout_minutes: int = 0,
    after_work_buffer_minutes: int = 30,
) -> dict:
    """Plan sleep around late work while respecting tomorrow's commitments."""
    tomorrow = now.date() + timedelta(days=1)
    tomorrow_events = [
        event for event in events
        if event.start.date() == tomorrow and event.important
    ]
    first_event = min(
        (event.start for event in tomorrow_events),
        default=None,
    )
    latest_wake = (
        first_event - timedelta(minutes=wake_routine_minutes + morning_workout_minutes)
        if first_event
        else datetime.combine(tomorrow, time(10, 0))
    )

    tonight_end = datetime.combine(tomorrow, time(0, 0))
    late_work = [
        event for event in events
        if event.category == "work"
        and event.start.date() == now.date()
        and event.end >= datetime.combine(now.date(), time(22, 0))
    ]
    preferred_bedtime = datetime.combine(tomorrow, time(1, 15))
    if late_work:
        latest_shift_end = max(event.end for event in late_work)
        preferred_bedtime = max(
            preferred_bedtime,
            latest_shift_end + timedelta(minutes=after_work_buffer_minutes + wind_down_minutes),
        )

    required_bedtime = latest_wake - timedelta(hours=desired_sleep_hours)
    bedtime = min(preferred_bedtime, required_bedtime) if first_event else preferred_bedtime
    wake_up_time = min(latest_wake, bedtime + timedelta(hours=desired_sleep_hours))
    wind_down_time = bedtime - timedelta(minutes=wind_down_minutes)
    sleep_hours = (wake_up_time - bedtime).total_seconds() / 3600
    note = (
        f"Late shift recovery plan; target {sleep_hours:.1f} hours"
        if late_work
        else f"Target {sleep_hours:.1f} hours before tomorrow's first commitment"
    )
    return {
        "wind_down_time": wind_down_time,
        "bedtime": bedtime,
        "wake_up_time": wake_up_time,
        "sleep_hours": sleep_hours,
        "note": note,
    }


def _earliest_possible_bedtime(now: datetime, events: list[CalendarEvent]) -> datetime:
    tomorrow = now.date() + timedelta(days=1)
    late_work = [
        event for event in events
        if event.category == "work"
        and event.start.date() == now.date()
        and event.end >= datetime.combine(now.date(), time(22, 0))
    ]
    if not late_work:
        return now
    return max(event.end for event in late_work) + timedelta(minutes=75)


def alert_level(due_at: datetime, now: datetime) -> AlertLevel:
    minutes = (due_at - now).total_seconds() / 60
    if minutes <= 0:
        return AlertLevel.CRITICAL
    if minutes <= 30:
        return AlertLevel.CRITICAL
    if minutes <= 120:
        return AlertLevel.URGENT
    if minutes <= 24 * 60:
        return AlertLevel.SOON
    return AlertLevel.NORMAL


def build_alerts(
    now: datetime,
    events: list[CalendarEvent],
    assignments: list[Assignment],
    chores: list[Chore],
    workout: Workout | None,
) -> list[Alert]:
    alerts = []
    for assignment in assignments:
        if not assignment.submitted and assignment.due_at <= now + timedelta(hours=24):
            alerts.append(
                Alert(
                    f"assignment-{assignment.id}",
                    f"{assignment.title} is {assignment_bucket(assignment.due_at, now)}",
                    alert_level(assignment.due_at, now),
                    assignment.due_at,
                    "Open assignment",
                )
            )
    for event in events:
        if now < event.start <= now + timedelta(hours=2):
            alerts.append(
                Alert(
                    f"event-{event.id}",
                    f"{event.title} starts soon",
                    alert_level(event.start, now),
                    event.start,
                    "View schedule",
                )
            )
    for chore in chores:
        if chore.due_at and not chore.completed and chore.due_at <= now + timedelta(hours=24):
            alerts.append(
                Alert(
                    f"chore-{chore.id}",
                    chore.title,
                    alert_level(chore.due_at, now),
                    chore.due_at,
                    "Mark complete",
                )
            )
    rank = {AlertLevel.CRITICAL: 0, AlertLevel.URGENT: 1, AlertLevel.SOON: 2, AlertLevel.NORMAL: 3}
    return sorted(alerts, key=lambda alert: rank[alert.level])
