from __future__ import annotations

import json
import re
from pathlib import Path


class GroceryStore:
    def __init__(self, path: Path):
        self.path = path

    def add(self, name: str, quantity: str = "1") -> dict:
        items = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        clean_name = name.strip()
        item = {
            "id": f"g-{re.sub(r'[^a-z0-9]+', '-', clean_name.lower()).strip('-')}-{len(items)+1}",
            "name": clean_name,
            "quantity": quantity,
            "checked": False,
        }
        items.append(item)
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")
        return item
