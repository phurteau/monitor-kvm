"""
Read-modify-write store for settings.json (the app's "localStorage").

Every module that persists a preference (theme, accent, minimal-bar position,
last-used mode) shares one JSON file at data_dir()/settings.json. Writing must
therefore MERGE into the existing file, never overwrite it wholesale, or one
subsystem would silently clobber another's keys (the bug that shipped when
theme.py did a bare json.dump of only {"theme","accent"}).

The API is intentionally tiny:
  load()            -> the whole dict (empty on missing/corrupt file)
  get(key, default) -> one value
  set(key, value)   -> merge one key
  update(**kwargs)  -> merge several keys at once

All reads tolerate a missing or corrupt file (OSError, json.JSONDecodeError)
and all writes swallow OSError, matching the original best-effort behaviour so
a locked or read-only settings file never crashes the app.
"""

from __future__ import annotations

import json
import os

from apppaths import data_dir

SETTINGS_PATH = os.path.join(data_dir(), "settings.json")


def load() -> dict:
    """Return the full settings dict, or {} if the file is missing/corrupt."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get(key, default=None):
    """Return a single setting value, or default if absent."""
    return load().get(key, default)


def _write(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def update(**kwargs) -> dict:
    """Merge the given key/values into settings.json, preserving other keys."""
    data = load()
    data.update(kwargs)
    _write(data)
    return data


def set(key, value) -> dict:  # noqa: A001 - deliberate dict-like verb
    """Merge one key/value into settings.json, preserving other keys."""
    return update(**{key: value})
