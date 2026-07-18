"""
Headless one-click workspace apply.

Usage:
    pythonw switch.py "Work"
    python  switch.py "Personal"

Intended to be wired to a desktop shortcut so a single click flips every
monitor to that workspace's inputs with no window. Writes a short log line
to switch.log next to this file.
"""

from __future__ import annotations

import datetime
import os
import sys

import ddc
import profiles
from apppaths import data_dir
from vcp_inputs import label_for_value

LOG_PATH = os.path.join(data_dir(), "switch.log")


def _log(msg: str) -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def apply_workspace(name: str) -> int:
    store = profiles.load()
    ws = store.get(name)
    if not ws:
        available = ", ".join(w.name for w in store.workspaces) or "(none)"
        _log(f"Workspace '{name}' not found. Available: {available}")
        return 2

    try:
        live = {m.stable_id: m for m in ddc.list_monitors()}
    except ddc.DDCError as e:
        _log(f"DDC error: {e}")
        return 3

    ok = skipped = 0
    for a in ws.assignments:
        m = live.get(a.monitor_id)
        if not m:
            skipped += 1
            _log(f"  skip: '{a.monitor_label}' ({a.monitor_id}) not attached")
            continue
        try:
            ddc.set_input_source(m, a.value)
            ok += 1
            _log(f"  set: {a.monitor_label} -> {a.value_label or label_for_value(a.value)} (0x{a.value:02X})")
        except Exception as e:  # noqa: BLE001
            skipped += 1
            _log(f"  fail: {a.monitor_label}: {e}")

    _log(f"Workspace '{name}': {ok} switched, {skipped} skipped.")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) < 2:
        store = profiles.load()
        names = ", ".join(w.name for w in store.workspaces) or "(no workspaces yet)"
        _log(f"No workspace given. Usage: switch.py \"<name>\"  |  available: {names}")
        return 2
    return apply_workspace(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
