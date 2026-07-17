"""Load/save workspace profiles to profiles.json next to this file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(_HERE, "profiles.json")


@dataclass
class Assignment:
    monitor_id: str          # stable id (serial or short id)
    monitor_label: str       # friendly name e.g. "Left monitor"
    value: int               # raw VCP 0x60 value to set
    value_label: str = ""    # friendly connection name e.g. "DisplayPort"


@dataclass
class Workspace:
    name: str
    assignments: list[Assignment] = field(default_factory=list)


@dataclass
class Store:
    workspaces: list[Workspace] = field(default_factory=list)

    def get(self, name: str) -> Optional[Workspace]:
        for w in self.workspaces:
            if w.name.lower() == name.lower():
                return w
        return None

    def upsert(self, ws: Workspace) -> None:
        existing = self.get(ws.name)
        if existing:
            existing.assignments = ws.assignments
        else:
            self.workspaces.append(ws)

    def remove(self, name: str) -> None:
        self.workspaces = [w for w in self.workspaces if w.name.lower() != name.lower()]


def load() -> Store:
    if not os.path.exists(PROFILES_PATH):
        return Store()
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return Store()
    workspaces = []
    for w in raw.get("workspaces", []):
        assigns = [
            Assignment(
                monitor_id=a.get("monitor_id", ""),
                monitor_label=a.get("monitor_label", ""),
                value=int(a.get("value", 0)),
                value_label=a.get("value_label", ""),
            )
            for a in w.get("assignments", [])
        ]
        workspaces.append(Workspace(name=w.get("name", "Workspace"), assignments=assigns))
    return Store(workspaces=workspaces)


def save(store: Store) -> None:
    data = {
        "workspaces": [
            {
                "name": w.name,
                "assignments": [asdict(a) for a in w.assignments],
            }
            for w in store.workspaces
        ]
    }
    with open(PROFILES_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
