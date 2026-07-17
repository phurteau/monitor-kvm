"""
Create desktop shortcuts for one-click workspace switching.

For every workspace in profiles.json it creates a desktop shortcut named
"Monitors - <Workspace>.lnk" that runs `pythonw switch.py "<Workspace>"`
with no console window. Also creates a shortcut that opens the setup GUI.

Run:  python make_shortcuts.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import profiles

_HERE = os.path.dirname(os.path.abspath(__file__))


def _pythonw() -> str:
    # Prefer pythonw.exe (no console) sitting next to python.exe.
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def _make_lnk(lnk_path: str, target: str, args: str, workdir: str, icon: str = "") -> None:
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{lnk_path}')
$s.TargetPath = '{target}'
$s.Arguments = '{args}'
$s.WorkingDirectory = '{workdir}'
{"$s.IconLocation = '" + icon + "'" if icon else ""}
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def main() -> int:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        # OneDrive-redirected desktop fallback
        alt = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        desktop = alt if os.path.isdir(alt) else desktop

    pyw = _pythonw()
    py = sys.executable
    switch_py = os.path.join(_HERE, "switch.py")
    app_py = os.path.join(_HERE, "app.py")

    store = profiles.load()
    made = []
    for w in store.workspaces:
        lnk = os.path.join(desktop, f"Monitors - {w.name}.lnk")
        _make_lnk(lnk, pyw, f'"{switch_py}" "{w.name}"', _HERE)
        made.append(lnk)

    # setup GUI shortcut
    setup_lnk = os.path.join(desktop, "Monitor Switcher (Setup).lnk")
    _make_lnk(setup_lnk, pyw, f'"{app_py}"', _HERE)
    made.append(setup_lnk)

    print("Created shortcuts:")
    for m in made:
        print("  " + m)
    if not store.workspaces:
        print("\nNote: no workspaces defined yet - only the Setup shortcut was made.")
        print("Open Setup, capture your inputs as 'Personal' and 'Work', then re-run this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
