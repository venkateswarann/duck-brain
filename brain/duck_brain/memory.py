"""Tiny persistent memory: names and facts people tell the duck."""

from __future__ import annotations

import json
import os
import time
from typing import Any


class Memory:
    def __init__(self, path: str, max_items: int = 30) -> None:
        self.path = path
        self.max_items = max_items
        self.items: dict[str, dict[str, Any]] = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.items = json.load(f)
            except (OSError, json.JSONDecodeError):
                self.items = {}

    def remember(self, key: str, value: str) -> bool:
        """Store a fact; returns False if it was already known."""
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        known = self.items.get(key)
        if known and known["value"].lower() == value.lower():
            return False
        self.items[key] = {"value": value, "ts": time.time()}
        if len(self.items) > self.max_items:  # forget the oldest
            oldest = sorted(self.items, key=lambda k: self.items[k]["ts"])
            for k in oldest[: len(self.items) - self.max_items]:
                del self.items[k]
        self._save()
        return True

    def summary(self) -> str:
        if not self.items:
            return "You don't remember anything about anyone yet."
        recent = sorted(self.items.items(), key=lambda kv: kv[1]["ts"], reverse=True)
        return "Things you remember: " + "; ".join(f"{k} = {v['value']}" for k, v in recent)

    def _save(self) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.items, f, indent=2)
        os.replace(tmp, self.path)
