from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .dashboard import build_dashboard
from .hydration import HydrationStore
from .checklists import ChecklistStore
from .sync_manager import SyncManager
from .groceries import GroceryStore


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
HYDRATION_STORE = HydrationStore(ROOT / "mock_data" / "hydration_state.json")
CHECKLIST_STORE = ChecklistStore(ROOT / "mock_data" / "checklist_state.json")
GROCERY_STORE = GroceryStore(ROOT / "mock_data" / "groceries.json")
SYNC_MANAGER = SyncManager(ROOT / "mock_data")


class DashboardEvents:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0

    def publish(self):
        with self.condition:
            self.version += 1
            self.condition.notify_all()

    def wait(self, version: int, timeout: int = 25) -> int:
        with self.condition:
            self.condition.wait_for(lambda: self.version != version, timeout)
            return self.version


EVENTS = DashboardEvents()
SYNC_MANAGER.subscribe(EVENTS.publish)


class LifeHubHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/dashboard":
            payload = json.dumps(build_dashboard(sync_manager=SYNC_MANAGER).to_dict(), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            version = EVENTS.version
            try:
                while True:
                    version = EVENTS.wait(version)
                    self.wfile.write(f"event: dashboard\ndata: {version}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/hydration/add":
            self._send_json(HYDRATION_STORE.add_bottle(datetime.now()))
            EVENTS.publish()
            return
        if path == "/api/hydration/reset":
            self._send_json(HYDRATION_STORE.reset(datetime.now()))
            EVENTS.publish()
            return
        if path == "/api/checklist/toggle":
            body = self._read_json()
            self._send_json(CHECKLIST_STORE.toggle(body["group"], body["id"], datetime.now()))
            EVENTS.publish()
            return
        if path == "/api/checklist/group":
            body = self._read_json()
            self._send_json(CHECKLIST_STORE.set_group(body["group"], body["ids"], body["complete"], datetime.now()))
            EVENTS.publish()
            return
        if path == "/api/sync":
            self._send_json(SYNC_MANAGER.sync_all())
            return
        if path == "/api/command":
            body = self._read_json()
            command = body.get("command", "").strip()
            lowered = command.lower()
            if lowered in {"log bottle", "add bottle", "hydration"}:
                result = {"message": "Bottle logged", "action": "hydration", "data": HYDRATION_STORE.add_bottle(datetime.now())}
            elif lowered in {"sync", "sync now", "refresh"}:
                result = {"message": "Synchronization complete", "action": "sync", "data": SYNC_MANAGER.sync_all()}
            elif lowered.startswith("add ") and (" grocery" in lowered or " groceries" in lowered):
                name = command[4:]
                for suffix in (" to groceries", " to grocery list", " grocery", " groceries"):
                    if name.lower().endswith(suffix):
                        name = name[:-len(suffix)]
                        break
                result = {"message": f"Added {name.strip()} to groceries", "action": "grocery", "data": GROCERY_STORE.add(name)}
            else:
                result = {"message": "Try: week, today, log bottle, sync, or add milk to groceries", "action": "help"}
            EVENTS.publish()
            self._send_json(result)
            return
        self.send_error(404)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, value):
        from dataclasses import asdict
        from datetime import datetime

        payload = json.dumps(
            asdict(value) if hasattr(value, "__dataclass_fields__") else value,
            default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def run(host: str = "0.0.0.0", port: int = 8000):
    print(f"LifeHub dashboard: http://127.0.0.1:{port} (also available on your local network)")
    SYNC_MANAGER.start()
    ThreadingHTTPServer((host, port), LifeHubHandler).serve_forever()


if __name__ == "__main__":
    run()
