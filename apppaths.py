"""
Path helpers that work both when run as a .py script and when frozen into a
PyInstaller .exe.

  resource_dir() : where read-only bundled files live (e.g. tools/ControlMyMonitor.exe).
                   Frozen one-file exe extracts data to sys._MEIPASS; source runs
                   use the project directory.
  data_dir()     : a stable, user-writable folder for profiles.json / settings.json /
                   switch.log. Frozen exes must NOT write next to the exe (may be in
                   Program Files) or into _MEIPASS (temp, wiped each run), so use
                   %APPDATA%\\MonitorWorkspaceSwitcher. Source runs keep everything in
                   the project directory (unchanged behavior).
"""

from __future__ import annotations

import os
import sys

APP_DIR_NAME = "MonitorWorkspaceSwitcher"
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return _PROJECT_DIR


def data_dir() -> str:
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, APP_DIR_NAME)
    else:
        d = _PROJECT_DIR
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d
