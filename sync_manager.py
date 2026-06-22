from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from .calendar_ical import parse_work_ical
from .canvas_ical import parse_canvas_ical


DEFAULT_CONFIG = {
    "sync_interval_minutes": 15,
    "stale_after_hours": 24,
    "canvas_ical_url": "",
    "schedulefly_ical_url": "",
    "weather": {"latitude": 39.7555, "longitude": -105.2211, "label": "Golden"},
}


class SyncManager:
    """Refreshes supported feeds, caches weather, and reports source freshness."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.config_path = data_dir / "lifehub_config.json"
        self.weather_path = data_dir / "weather_cache.json"
        self.status_path = data_dir / "sync_status.json"
        self._lock = threading.Lock()
        self._listeners: list[callable] = []
        self._stop = threading.Event()
        self._ensure_config()

    def _ensure_config(self):
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    def config(self) -> dict:
        config = dict(DEFAULT_CONFIG)
        stored = json.loads(self.config_path.read_text(encoding="utf-8"))
        config.update(stored)
        config["weather"] = {**DEFAULT_CONFIG["weather"], **stored.get("weather", {})}
        return config

    def subscribe(self, listener):
        self._listeners.append(listener)

    def notify(self):
        for listener in self._listeners:
            listener()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="lifehub-sync").start()

    def stop(self):
        self._stop.set()

    def _run(self):
        self.sync_all()
        while not self._stop.wait(self.config()["sync_interval_minutes"] * 60):
            self.sync_all()

    def sync_all(self) -> dict:
        with self._lock:
            started = datetime.now()
            results = {}
            results["schedulefly"] = self._sync_schedulefly()
            results["canvas"] = self._sync_canvas()
            results["weather"] = self._sync_weather()
            status = {"last_attempt": started.isoformat(), "sources": results}
            self.status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        self.notify()
        return status

    def _sync_schedulefly(self) -> dict:
        url = self.config().get("schedulefly_ical_url", "").strip()
        if not url:
            return {"ok": True, "message": "Using imported Schedulefly snapshot"}
        try:
            text = self._fetch(url)
            rows = parse_work_ical(text)
            (self.data_dir / "work_schedule.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
            return {"ok": True, "message": f"Schedulefly updated: {len(rows)} shifts"}
        except Exception as exc:
            return {"ok": False, "message": f"Schedulefly sync failed: {exc}"}

    def _sync_canvas(self) -> dict:
        url = self.config().get("canvas_ical_url", "").strip()
        if not url:
            return {"ok": True, "message": "Using imported Canvas snapshot"}
        try:
            text = self._fetch(url)
            rows = parse_canvas_ical(text)
            (self.data_dir / "canvas_assignments.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
            return {"ok": True, "message": f"Canvas updated: {len(rows)} assignments"}
        except Exception as exc:
            return {"ok": False, "message": f"Canvas sync failed: {exc}"}

    def _sync_weather(self) -> dict:
        weather = self.config()["weather"]
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={weather['latitude']}&longitude={weather['longitude']}"
            "&current=temperature_2m,apparent_temperature,weather_code,precipitation,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FDenver&forecast_days=2"
        )
        try:
            raw = json.loads(self._fetch(url))
            current, daily = raw["current"], raw["daily"]
            payload = {
                "location": weather["label"],
                "temperature": round(current["temperature_2m"]),
                "feels_like": round(current["apparent_temperature"]),
                "condition": weather_label(current["weather_code"]),
                "wind_mph": round(current["wind_speed_10m"]),
                "precipitation": current["precipitation"],
                "today_high": round(daily["temperature_2m_max"][0]),
                "today_low": round(daily["temperature_2m_min"][0]),
                "tomorrow_high": round(daily["temperature_2m_max"][1]),
                "tomorrow_low": round(daily["temperature_2m_min"][1]),
                "tomorrow_precipitation_chance": daily["precipitation_probability_max"][1],
                "updated_at": datetime.now().isoformat(),
            }
            self.weather_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return {"ok": True, "message": "Weather updated"}
        except Exception as exc:
            return {"ok": False, "message": f"Weather sync failed: {exc}"}

    @staticmethod
    def _fetch(url: str) -> str:
        request = Request(url, headers={"User-Agent": "LifeHub/1.0"})
        with urlopen(request, timeout=12) as response:
            return response.read().decode("utf-8")

    def weather(self) -> dict | None:
        if not self.weather_path.exists():
            return None
        return json.loads(self.weather_path.read_text(encoding="utf-8"))

    def freshness(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        stale_after = timedelta(hours=self.config()["stale_after_hours"])
        sources = {}
        for name, filename in {
            "Schedulefly": "work_schedule.json",
            "Canvas": "canvas_assignments.json",
            "Weather": "weather_cache.json",
        }.items():
            path = self.data_dir / filename
            if not path.exists():
                sources[name] = {"state": "missing", "age_minutes": None}
                continue
            updated = datetime.fromtimestamp(path.stat().st_mtime)
            age = now - updated
            sources[name] = {
                "state": "stale" if age > stale_after else "fresh",
                "age_minutes": max(0, round(age.total_seconds() / 60)),
                "updated_at": updated.isoformat(),
            }
        states = [item["state"] for item in sources.values()]
        overall = "stale" if "stale" in states or "missing" in states else "fresh"
        return {"overall": overall, "sources": sources}


def weather_label(code: int) -> str:
    if code == 0:
        return "Clear"
    if code in {1, 2, 3}:
        return "Partly cloudy"
    if code in {45, 48}:
        return "Foggy"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if code in {95, 96, 99}:
        return "Thunderstorms"
    return "Mixed conditions"
