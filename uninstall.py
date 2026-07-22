"""
Uninstaller: fully removes everything Monitor Workspace Switcher leaves on a PC.

The app is portable (no Windows installer), so there is no MSI/registry install
entry to remove. What it DOES create, and what this removes:

  * %APPDATA%\\MonitorWorkspaceSwitcher\\: profiles.json, settings.json, switch.log
  * Desktop shortcuts created by make_shortcuts.py:
        "Monitors - <workspace>.lnk"  and  "Monitor Switcher (Setup).lnk"
        (on the normal Desktop and a OneDrive-redirected Desktop)
  * Any HKCU "Run" startup registry value pointing at the app (defensive: the
    app doesn't create one, but a user might have added one; we clean it if so).
  * Optionally the app's own folder / executable.

Usage:
  Uninstall.exe                 -> GUI confirmation, then removes everything.
  python uninstall.py --yes     -> headless, no prompt.
  python uninstall.py --keep-app-folder   -> don't delete the app folder itself.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

APP_DIR_NAME = "MonitorWorkspaceSwitcher"
SHORTCUT_PATTERNS = ["Monitors - *.lnk", "Monitor Switcher (Setup).lnk"]
# Registry Run value names we consider "ours" if present.
RUN_VALUE_NAMES = ["MonitorWorkspaceSwitcher", "Monitor Workspace Switcher"]


def _appdata_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def _desktops() -> list[str]:
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
    ]
    od = os.environ.get("OneDrive")
    if od:
        cands.append(os.path.join(od, "Desktop"))
    seen, out = set(), []
    for c in cands:
        if c not in seen and os.path.isdir(c):
            seen.add(c)
            out.append(c)
    return out


def find_targets(app_dir: str | None):
    """Return a dict describing everything that would be removed."""
    data = _appdata_dir()
    shortcuts = []
    for desk in _desktops():
        for pat in SHORTCUT_PATTERNS:
            shortcuts.extend(glob.glob(os.path.join(desk, pat)))

    reg = _find_run_keys()

    return {
        "data_dir": data if os.path.isdir(data) else None,
        "shortcuts": sorted(set(shortcuts)),
        "registry": reg,
        "app_dir": app_dir if app_dir and os.path.isdir(app_dir) else None,
    }


def _find_run_keys():
    """Find any HKCU\\...\\Run values that look like ours. Returns list of names."""
    found = []
    if os.name != "nt":
        return found
    try:
        import winreg
    except ImportError:
        return found
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_READ)
    except OSError:
        return found
    try:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            low = f"{name} {value}".lower()
            if name in RUN_VALUE_NAMES or APP_DIR_NAME.lower() in low or "monitorworkspaceswitcher" in low:
                found.append(name)
    finally:
        winreg.CloseKey(key)
    return found


def _delete_run_keys(names):
    removed = []
    if not names or os.name != "nt":
        return removed
    try:
        import winreg
    except ImportError:
        return removed
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return removed
    try:
        for n in names:
            try:
                winreg.DeleteValue(key, n)
                removed.append(n)
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)
    return removed


def _self_delete_app_dir(app_dir: str):
    """Schedule removal of the app folder. If we're running from inside it
    (frozen exe), spawn a detached batch that waits for us to exit, then deletes.
    Otherwise remove it directly."""
    running_inside = False
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        running_inside = os.path.normcase(exe_dir).startswith(os.path.normcase(app_dir))
    except Exception:  # noqa: BLE001
        pass

    if not running_inside:
        try:
            shutil.rmtree(app_dir, ignore_errors=True)
            return "removed"
        except Exception:  # noqa: BLE001
            return "failed"

    # We're inside it, so use a delayed batch so the folder can be deleted after exit.
    import tempfile
    bat = os.path.join(tempfile.gettempdir(), "mkvm_uninstall.bat")
    target = app_dir
    with open(bat, "w", encoding="ascii", errors="ignore") as fh:
        fh.write("@echo off\r\n")
        fh.write("ping 127.0.0.1 -n 3 >nul\r\n")           # ~2s wait for us to exit
        fh.write(f'rmdir /s /q "{target}"\r\n')
        fh.write(f'del "%~f0"\r\n')                          # delete the batch itself
    try:
        import subprocess
        subprocess.Popen(["cmd", "/c", bat],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
        return "scheduled"
    except Exception:  # noqa: BLE001
        return "failed"


def run_uninstall(remove_app_folder: bool = True, app_dir: str | None = None):
    """Perform the removal. Returns a list of human-readable result lines."""
    targets = find_targets(app_dir)
    lines = []

    # 1. app data
    if targets["data_dir"]:
        shutil.rmtree(targets["data_dir"], ignore_errors=True)
        gone = not os.path.isdir(targets["data_dir"])
        lines.append(("Removed app data: " if gone else "Could not remove: ") + targets["data_dir"])
    else:
        lines.append("No app data folder found (nothing to remove).")

    # 2. shortcuts
    if targets["shortcuts"]:
        for s in targets["shortcuts"]:
            try:
                os.remove(s)
                lines.append("Removed shortcut: " + os.path.basename(s))
            except OSError:
                lines.append("Could not remove shortcut: " + s)
    else:
        lines.append("No desktop shortcuts found.")

    # 3. registry startup entries (defensive)
    if targets["registry"]:
        removed = _delete_run_keys(targets["registry"])
        for n in removed:
            lines.append("Removed startup registry value: " + n)
        leftover = [n for n in targets["registry"] if n not in removed]
        for n in leftover:
            lines.append("Could not remove registry value: " + n)
    else:
        lines.append("No app registry entries found.")

    # 4. app folder itself
    if remove_app_folder and targets["app_dir"]:
        status = _self_delete_app_dir(targets["app_dir"])
        if status == "scheduled":
            lines.append("App folder will be deleted right after this window closes.")
        elif status == "removed":
            lines.append("Removed app folder: " + targets["app_dir"])
        else:
            lines.append("Could not remove app folder: " + targets["app_dir"]
                         + " (delete it manually).")
    return lines


# ---------------- entry points ----------------
def _gui():
    import tkinter as tk
    from tkinter import messagebox

    # detect the app folder if we're a frozen exe living beside the app
    app_dir = None
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))

    root = tk.Tk()
    root.withdraw()
    targets = find_targets(app_dir)

    summary = ["This will remove Monitor Workspace Switcher and all its data:", ""]
    summary.append("  Settings & workspaces: " + (targets["data_dir"] or "none found"))
    summary.append("  Desktop shortcuts: " + (str(len(targets["shortcuts"])) + " found"
                                              if targets["shortcuts"] else "none found"))
    summary.append("  Registry entries: " + (", ".join(targets["registry"]) if targets["registry"] else "none"))
    if targets["app_dir"]:
        summary.append("  App folder: " + targets["app_dir"])
    summary.append("")
    summary.append("This cannot be undone. Continue?")

    if not messagebox.askyesno("Uninstall Monitor Workspace Switcher",
                               "\n".join(summary), icon="warning"):
        root.destroy()
        return 1

    lines = run_uninstall(remove_app_folder=True, app_dir=app_dir)
    messagebox.showinfo("Uninstall complete", "\n".join(lines))
    root.destroy()
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--yes" in argv or "-y" in argv:
        keep = "--keep-app-folder" in argv
        app_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else None
        for ln in run_uninstall(remove_app_folder=not keep, app_dir=app_dir):
            print(ln)
        return 0
    return _gui()


if __name__ == "__main__":
    raise SystemExit(main())
