import unittest
from datetime import datetime, timedelta
from pathlib import Path

from lifehub.dashboard import build_dashboard
from lifehub.data_loader import MockDataLoader
from lifehub.canvas_ical import parse_canvas_ical
from lifehub.calendar_ical import parse_work_ical
from lifehub.hydration import HydrationStore
from lifehub.checklists import ChecklistStore
from lifehub.models import AlertLevel, CalendarEvent, Workout
from lifehub.scheduler import adaptive_routine_plan, alert_level, build_alerts, build_timeline, calculate_sleep_plan, calculate_wind_down, detect_conflicts, next_school_work, next_shift, schedule_workout
from lifehub.sync_manager import SyncManager, weather_label
from lifehub.groceries import GroceryStore
from lifehub.schedulefly_page import parse_personal_schedulefly_rows, parse_personal_schedulefly_text, parse_schedulefly_rows, parse_schedulefly_text


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 11, 8, 0)

    def test_lift_is_scheduled_before_target(self):
        workout = Workout("lift", "Lift", "Thursday", 90, True)
        result = schedule_workout(self.now, workout, [])
        self.assertIsNotNone(result.recommended_start)
        self.assertEqual(result.recommended_start, datetime(2026, 6, 11, 10))

    def test_long_lift_starts_early_enough_to_finish_by_noon(self):
        workout = Workout("long-lift", "Long Lift", "Thursday", 150, True)
        result = schedule_workout(self.now, workout, [])
        self.assertEqual(result.recommended_start, datetime(2026, 6, 11, 9, 30))
        self.assertEqual(
            result.recommended_start + timedelta(minutes=result.duration_minutes),
            datetime(2026, 6, 11, 12),
        )

    def test_missed_workout_still_appears_as_planned_timeline_item(self):
        now = datetime(2026, 6, 11, 14)
        workout = schedule_workout(now, Workout("lift", "Lift", "Thursday", 150, True), [])
        timeline = build_timeline(now, [], workout, [], calculate_sleep_plan(now, []))
        planned = next(item for item in timeline if item["category"] == "workout")
        self.assertEqual(planned["start"], "2026-06-11T09:30:00")
        self.assertIn("(planned)", planned["title"])

    def test_backup_created_when_morning_is_full(self):
        busy = [CalendarEvent("busy", "Busy", self.now.replace(hour=5), self.now.replace(hour=12), "event")]
        workout = Workout("lift", "Lift", "Thursday", 90, True)
        result = schedule_workout(self.now, workout, busy)
        self.assertIsNone(result.recommended_start)
        self.assertIn("home strength", result.backup_plan)

    def test_adaptive_routine_reserves_pre_close_lift_window(self):
        workout = Workout("lift", "Lift", "Friday", 150, True)
        plan = adaptive_routine_plan(self.now, [], workout)
        scheduled = schedule_workout(plan["wake_up_time"], workout, [])
        self.assertGreaterEqual(plan["sleep_hours"], 8.5)
        self.assertLessEqual(plan["wake_up_time"], scheduled.recommended_start - timedelta(hours=1))
        self.assertLessEqual(
            scheduled.recommended_start + timedelta(minutes=workout.duration_minutes),
            datetime(2026, 6, 12, 12),
        )

    def test_adaptive_routine_reserves_hour_before_non_lift_workout(self):
        workout = Workout("tempo", "Tempo", "Friday", 90, False)
        plan = adaptive_routine_plan(self.now, [], workout)
        scheduled = schedule_workout(plan["wake_up_time"], workout, [])
        self.assertEqual(scheduled.recommended_start, datetime(2026, 6, 12, 10))
        self.assertEqual(plan["wake_up_time"], datetime(2026, 6, 12, 9))
        self.assertEqual(plan["bedtime"], datetime(2026, 6, 12, 0, 15))

    def test_late_shift_and_tomorrow_lift_reports_sleep_conflict(self):
        now = datetime(2026, 6, 11, 18)
        shift = CalendarEvent("late", "Late shift", now, datetime(2026, 6, 12, 2), "work")
        workout = Workout("lift", "Lift", "Friday", 150, True)
        plan = adaptive_routine_plan(now, [shift], workout)
        scheduled = schedule_workout(plan["wake_up_time"], workout, [shift])
        conflicts = detect_conflicts(now, [shift], scheduled, plan)
        self.assertLess(plan["sleep_hours"], 8.5)
        self.assertIn("sleep-shortfall", [conflict["id"] for conflict in conflicts])

    def test_conflict_detection_finds_overlapping_events(self):
        first = CalendarEvent("a", "Class", self.now, self.now + timedelta(hours=2), "class")
        second = CalendarEvent("b", "Work", self.now + timedelta(hours=1), self.now + timedelta(hours=3), "work")
        conflicts = detect_conflicts(self.now, [first, second], None, calculate_sleep_plan(self.now, []))
        self.assertIn("overlap-a-b", [conflict["id"] for conflict in conflicts])

    def test_actual_workout_plan_loads_structured_sections(self):
        workouts = MockDataLoader(Path("mock_data")).load_workouts()
        monday = next(workout for workout in workouts if workout.weekday == "Monday")
        sunday = next(workout for workout in workouts if workout.weekday == "Sunday")
        self.assertTrue(monday.includes_lifting)
        self.assertEqual(monday.sections[1].name, "Sprint Work")
        self.assertIn("4 x 20m at 90%", monday.sections[1].items)
        self.assertIn("Abbreviated lower-body", monday.backup_plan_template)
        self.assertTrue(sunday.is_rest_day)

    def test_actual_workout_uses_day_specific_backup(self):
        workout = next(
            workout for workout in MockDataLoader(Path("mock_data")).load_workouts()
            if workout.weekday == "Thursday"
        )
        busy = [CalendarEvent("busy", "Busy", self.now.replace(hour=5), self.now.replace(hour=12), "event")]
        result = schedule_workout(self.now, workout, busy)
        self.assertIn("penultimate drills", result.backup_plan)
        alerts = build_alerts(self.now, busy, [], [], result)
        self.assertNotIn("workout-backup", [alert.id for alert in alerts])

    def test_schedulefly_snapshot_loads_real_dates_and_overnight_shifts(self):
        events = MockDataLoader(Path("mock_data")).load_events(self.now)
        wednesday_library = next(event for event in events if event.id == "schedulefly-2026-06-17-library")
        self.assertEqual(wednesday_library.start, datetime(2026, 6, 17, 17, 0))
        self.assertEqual(wednesday_library.end, datetime(2026, 6, 18, 0, 0))
        self.assertEqual(wednesday_library.source, "schedulefly-snapshot")

    def test_next_shift_is_reported_separately(self):
        events = MockDataLoader(Path("mock_data")).load_events(self.now)
        result = next_shift(self.now, events)
        self.assertEqual(result["title"], "Work: Event")
        self.assertEqual(result["at"], "2026-06-16T12:00:00")

    def test_no_upcoming_school_work_returns_none(self):
        assignments = MockDataLoader(Path("mock_data")).load_assignments(self.now)
        self.assertIsNone(next_school_work(self.now, assignments))

    def test_canvas_ical_parser_handles_empty_and_assignment_feeds(self):
        empty = "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        event = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
            "UID:assignment-1\r\nSUMMARY:Lab 1 [Circuits]\r\n"
            "DTSTART:20260615T235900\r\nURL:https://example.test/assignment\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        self.assertEqual(parse_canvas_ical(empty), [])
        parsed = parse_canvas_ical(event)
        self.assertEqual(parsed[0]["title"], "Lab 1")
        self.assertEqual(parsed[0]["course"], "Circuits")

    def test_work_ical_parser_converts_schedulefly_events(self):
        feed = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
            "UID:shift-1\r\nSUMMARY:Dinner Support\r\n"
            "DTSTART:20260616T170000\r\nDTEND:20260617T000000\r\n"
            "LOCATION:Library\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        row = parse_work_ical(feed)[0]
        self.assertEqual(row["title"], "Work: Dinner Support")
        self.assertEqual(row["date"], "2026-06-16")
        self.assertEqual(row["start_time"], "17:00")
        self.assertEqual(row["end_time"], "00:00")

    def test_schedulefly_page_parser_extracts_employee_row(self):
        rows = [
            ["Employee", "Today", "Tuesday\nJun 16", "Wednesday\nJun 17"],
            ["Hafner, Vaughn", "", "12:00PM - 4:00PM\nEvent\n[Giveup Shift]", "5:00PM - 12:00AM\nLibrary"],
        ]
        shifts = parse_schedulefly_rows(rows, today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 2)
        self.assertEqual(shifts[0]["date"], "2026-06-16")
        self.assertEqual(shifts[0]["start_time"], "12:00")
        self.assertEqual(shifts[0]["location"], "Event")

    def test_schedulefly_parser_matches_first_name(self):
        rows = [
            ["Employee", "Today", "Tuesday\nJun 16"],
            ["Vaughn Hafner", "", "12:00PM - 4:00PM\nEvent"],
        ]
        shifts = parse_schedulefly_rows(rows, employee_name="Vaughn", today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 1)
        self.assertEqual(shifts[0]["location"], "Event")

    def test_schedulefly_text_parser_extracts_employee_row(self):
        text = (
            "Employee\tToday\tTuesday\nJun 16\tWednesday\nJun 17\n"
            "Hafner, Vaughn\t\t12:00PM - 4:00PM\nEvent\n[Giveup Shift]\t5:00PM - 12:00AM\nLibrary\n"
        )
        shifts = parse_schedulefly_text(text, today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 2)
        self.assertEqual(shifts[1]["date"], "2026-06-17")
        self.assertEqual(shifts[1]["location"], "Library")

    def test_schedulefly_home_parser_extracts_personal_schedule(self):
        text = (
            "My Schedule\n"
            "Tuesday Jun 16\n12:00PM - 4:00PM\nEvent\n"
            "Wednesday Jun 17\n5:00PM - 12:00AM\nLibrary\n"
        )
        shifts = parse_personal_schedulefly_text(text, today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 2)
        self.assertEqual(shifts[0]["date"], "2026-06-16")
        self.assertEqual(shifts[1]["location"], "Library")

    def test_schedulefly_home_table_parser_extracts_personal_week(self):
        rows = [
            ["Vaughn's Schedule"],
            ["Mon\nJun 15", "Tue\nJun 16", "Wed\nJun 17", "Thu\nJun 18", "Fri\nJun 19", "Sat\nJun 20", "Sun\nJun 21"],
            [
                "",
                "Lunch\n12:00PM - 4:00PM\nEvent\n(Support)\nGiveup",
                "Dinner\n5:00PM - 12:00AM\nLibrary\n(Support)\nGiveup",
                "",
                "Dinner\n4:30PM - 12:00AM\nLibrary\n(Support)\nGiveup",
                "Dinner\n4:00PM - 12:00AM\nLibrary\n(Support)\nGiveup",
                "Dinner\n4:00PM - 12:00AM\nLibrary\n(Support)\nGiveup",
            ],
        ]
        shifts = parse_personal_schedulefly_rows(rows, today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 5)
        self.assertEqual(shifts[0]["date"], "2026-06-16")
        self.assertEqual(shifts[0]["location"], "Event")
        self.assertEqual(shifts[-1]["date"], "2026-06-21")

    def test_schedulefly_home_parser_scans_near_first_name(self):
        text = (
            "Welcome Vaughn\n"
            "Tuesday Jun 16\n12:00PM - 4:00PM Event\n"
            "Wednesday Jun 17\n5:00PM - 12:00AM Library\n"
        )
        shifts = parse_personal_schedulefly_text(text, today=datetime(2026, 6, 15).date())
        self.assertEqual(len(shifts), 2)
        self.assertEqual(shifts[0]["location"], "Event")

    def test_rest_day_has_no_scheduled_start(self):
        workout = Workout("off", "Off Day", "Sunday", 0, False, is_rest_day=True)
        result = schedule_workout(self.now, workout, [])
        self.assertIsNone(result.recommended_start)
        self.assertEqual(result.backup_plan, "")

    def test_alert_thresholds(self):
        self.assertEqual(alert_level(self.now + timedelta(minutes=20), self.now), AlertLevel.CRITICAL)
        self.assertEqual(alert_level(self.now + timedelta(minutes=90), self.now), AlertLevel.URGENT)
        self.assertEqual(alert_level(self.now + timedelta(hours=8), self.now), AlertLevel.SOON)

    def test_wind_down_uses_tomorrow_first_event(self):
        event = CalendarEvent("first", "First", datetime(2026, 6, 12, 9), datetime(2026, 6, 12, 10), "class")
        result = calculate_wind_down(self.now, [event])
        self.assertEqual(result, datetime(2026, 6, 11, 22, 30))

    def test_late_work_shift_creates_late_sleep_plan(self):
        shift = CalendarEvent(
            "close",
            "Closing shift",
            datetime(2026, 6, 11, 17),
            datetime(2026, 6, 12, 0),
            "work",
        )
        plan = calculate_sleep_plan(self.now, [shift])
        self.assertEqual(plan["wind_down_time"], datetime(2026, 6, 12, 0, 30))
        self.assertEqual(plan["bedtime"], datetime(2026, 6, 12, 1, 15))
        self.assertEqual(plan["wake_up_time"], datetime(2026, 6, 12, 10, 0))

    def test_very_late_shift_never_plans_bedtime_before_home(self):
        shift = CalendarEvent(
            "very-late",
            "Very late shift",
            datetime(2026, 6, 11, 18),
            datetime(2026, 6, 12, 2),
            "work",
        )
        plan = calculate_sleep_plan(self.now, [shift])
        self.assertEqual(plan["wind_down_time"], datetime(2026, 6, 12, 2, 30))
        self.assertEqual(plan["bedtime"], datetime(2026, 6, 12, 3, 15))

    def test_recurring_wednesday_trash_is_due_at_night(self):
        chores = MockDataLoader(Path("mock_data")).load_chores(datetime(2026, 6, 10, 12))
        trash = next(chore for chore in chores if chore.id == "trash")
        self.assertEqual(trash.due_at, datetime(2026, 6, 10, 21))

    def test_hydration_checkpoint_advances_and_persists(self):
        path = Path("mock_data/test_hydration_state.json")
        try:
            store = HydrationStore(path)
            initial = store.reset(datetime(2026, 6, 11, 9))
            first = store.add_bottle(datetime(2026, 6, 11, 10))
            second = store.add_bottle(datetime(2026, 6, 11, 13))
            self.assertEqual(initial.current_bottles, 0)
            self.assertEqual(first.current_bottles, 1)
            self.assertEqual(second.current_bottles, 2)
            self.assertGreater(second.next_checkpoint, first.next_checkpoint)
            self.assertEqual(store.load(datetime(2026, 6, 11, 13)).current_bottles, 2)
        finally:
            path.unlink(missing_ok=True)

    def test_checklist_toggle_and_complete_group(self):
        path = Path("mock_data/test_checklist_state.json")
        try:
            store = ChecklistStore(path)
            now = datetime(2026, 6, 11, 9)
            self.assertEqual(store.toggle("chores", "trash", now)["chores"], ["trash"])
            self.assertEqual(store.toggle("chores", "trash", now)["chores"], [])
            state = store.set_group("wake_up", ["stretch", "shower"], True, now)
            self.assertEqual(state["wake_up"], ["shower", "stretch"])
        finally:
            path.unlink(missing_ok=True)

    def test_dashboard_serializes(self):
        state = build_dashboard(self.now, Path("mock_data")).to_dict()
        self.assertIn("now", state)
        self.assertIn("assignments", state)
        self.assertIsNone(state["next_school_work"])
        self.assertEqual(state["next_shift"]["title"], "Work: Event")
        self.assertEqual(state["wake_up_routine"][0], "Stretch")
        self.assertEqual(len(state["chores"]), 1)
        self.assertIsInstance(state["generated_at"], str)
        self.assertEqual(state["tomorrow"]["date"], "2026-06-12")
        self.assertIn("sync_details", state)
        self.assertIn("timeline", state)
        self.assertIn("conflicts", state)
        self.assertEqual(len(state["week_calendar"]), 7)
        self.assertTrue(state["week_calendar"][0]["is_today"])
        self.assertIn("start", state["week_calendar"][0]["items"][0])
        self.assertIn("end", state["week_calendar"][0]["items"][0])

    def test_weather_codes_have_readable_labels(self):
        self.assertEqual(weather_label(0), "Clear")
        self.assertEqual(weather_label(95), "Thunderstorms")

    def test_sync_freshness_reports_sources(self):
        status = SyncManager(Path("mock_data")).freshness(datetime.now())
        self.assertIn("Schedulefly", status["sources"])
        self.assertIn(status["overall"], {"fresh", "stale"})

    def test_grocery_store_adds_item(self):
        path = Path("mock_data/test_groceries.json")
        try:
            item = GroceryStore(path).add("Milk")
            self.assertEqual(item["name"], "Milk")
            self.assertEqual(GroceryStore(path).add("Eggs")["id"], "g-eggs-2")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
