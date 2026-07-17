# Monitor Workspace Switcher - a software KVM for monitor inputs

One click flips **every monitor's active input** (DisplayPort ↔ HDMI ↔ etc.) over
**DDC/CI**, so the same set of screens can jump between machines - e.g. a
**Personal** PC on DisplayPort and a **Work** PC on HDMI - without touching the
monitors' physical buttons.

It talks to your monitors using the exact same channel their on‑screen menu uses:
the DDC/CI protocol, VCP feature code **`0x60` (Input Source)**.

The main window also shows a **live map of your display layout** - pulled straight
from Windows (Settings → Display → *Rearrange your displays*) - including each
monitor's position, resolution, **orientation** (a vertical/portrait panel is drawn
portrait), which one is primary, and the input each is currently on. **Click any
monitor box** to set/learn its input inline.

A **pure-black theme with `#00ff00` (green) accents** is used throughout, an optional
**system-tray icon** lets you switch workspaces without opening the window, and a
built-in **updater** shows a one-click banner when a new release is available.

---

## Why it has to "learn" your monitors

The command to select an input is standardized, but the **value** that means
"DisplayPort" or "HDMI" is **not**. Dell uses DP=`0x0F`, HDMI=`0x11`; many LG
panels use `0xD0`/`0x90`; Samsung differs again. So the app does not hard‑code
values - it **reads the current input off each monitor** and lets you save that
as a workspace. That works for any monitor OSD, not just a specific brand.

---

## Requirements

- Windows
- Python 3.9+ (standard library `tkinter`)
- **Optional:** `pip install pystray pillow` - enables the system-tray icon
  (the app runs fine without it, just without a tray).
- Two (or more) source machines physically connected to the monitors at the same
  time (that's what makes it a KVM - you flip which input is shown).
- **DDC/CI must be enabled** in each monitor's on‑screen menu (it usually is by
  default; look under *Settings / Others / OSD*).
- `tools\ControlMyMonitor.exe` (NirSoft) - bundled here; it's the reliable
  Windows DDC/CI backend.

---

## First‑time setup (do this once, on the rig with the monitors)

1. **Launch the app**: double‑click **`Monitor Switcher.cmd`** (or run
   `python app.py`).
2. Click **Detect Monitors** - you should see your attached displays and the
   input each is currently on.
3. Click **Setup / Edit Workspaces → Monitors & Capture tab**.
4. Sit at the machine you want to capture (so *its* input is the one currently
   shown on the monitors). Click **Refresh / Read current inputs**, then
   **Capture these as a new workspace…** and name it e.g. **`Personal`**.
5. Repeat from the other machine (or after switching), naming it **`Work`**.
   - If you can't easily capture from the other PC, just edit the workspace on
     the **Workspaces** tab and pick the input from the dropdown (e.g. `HDMI 1
     (standard 0x11)`), using **Test** to confirm it switches.
6. Back on the main window you'll now have big **Personal** / **Work** buttons.
   One click applies that workspace.








---

## True one‑click from the desktop

Run once:

```
python make_shortcuts.py
```

This drops desktop shortcuts:
- **Monitors - Personal** → flips all monitors to your Personal inputs
- **Monitors - Work** → flips all monitors to your Work inputs
- **Monitor Switcher (Setup)** → opens the GUI

Each switch shortcut runs headless (no window) via `switch.py`. You can pin them
to the taskbar / Start for a genuine single click.

Headless usage directly:

```
pythonw switch.py "Work"
python  switch.py "Personal"
```

Results are appended to `switch.log`.

---

## Switch from the system tray (no window)

If `pystray` + `pillow` are installed, a green monitor icon appears in the tray on
launch. **Right-click it** for a menu of your workspaces - click one to flip all
monitors instantly. **Closing the window minimizes to the tray** (it keeps running);
use the tray's **Quit** to exit fully, or **Open Switcher** to bring the window back.

## Set an input by clicking the map

On the layout map, **click any monitor box** to open a small inline panel where you
can pick an input (from the vendor reference list) and hit **Set input** to switch it
live, or **Test** to try values without closing. This doubles as the "learn" flow:
if a value lands on the wrong source, just try another.

## Updates

On launch (and via **Check for Updates**), the app asks GitHub whether a newer
release of `phurteau/monitor-kvm` exists. If so, a **green banner** appears at the
top: click **Download & Update** to fetch the release, apply it in place (your
`profiles.json` is preserved), then **Restart now** to finish. Uses only the Python
standard library - no extra dependency.

The update source is set in `version.py` (`GITHUB_OWNER` / `GITHUB_REPO`), and the
current app version is `VERSION` there - bump it and tag each GitHub release `vX.Y.Z`.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | GUI: display-layout map, click-to-set inputs, workspace buttons, capture & edit |
| `layout.py` | Reads the live Windows display arrangement (position, size, orientation, primary) via Win32 |
| `tray.py` | Optional system-tray icon for switching workspaces without the window |
| `updater.py` | Checks GitHub Releases and applies one-click updates in place |
| `version.py` | Current `VERSION` and the GitHub repo the updater checks |
| `switch.py` | Headless one‑click apply of a named workspace |
| `make_shortcuts.py` | Generates desktop shortcuts per workspace |
| `ddc.py` | DDC/CI backend (wraps ControlMyMonitor.exe) |
| `vcp_inputs.py` | Reference table of input‑source values across vendors |
| `profiles.py` | Load/save `profiles.json` |
| `profiles.json` | Your saved workspaces (created after first capture) |
| `tools\ControlMyMonitor.exe` | NirSoft DDC/CI tool (backend) |
| `Monitor Switcher.cmd` | No‑console GUI launcher |

---

## Troubleshooting

- **"No monitors detected"** - Make sure displays are connected and **DDC/CI is
  ON** in each monitor's OSD. Some KVMs/USB‑C docks/adapters block DDC/CI.
- **Input reads as "unreadable"** - that monitor isn't answering DDC/CI on VCP
  `0x60`; check the OSD DDC/CI setting, or connect it more directly.
- **A monitor switches to the wrong input** - the saved value is wrong for that
  panel. Edit the workspace, pick another value from the dropdown, and use
  **Test** until it lands on the right input.
- **Switching away loses your view** - expected: you're now looking at the other
  machine's input. Switch back with that machine's workspace shortcut, or use the
  monitor's physical buttons as a fallback.
- **Identical monitors** - if two panels report the same short ID and no serial,
  they can be ambiguous; the app falls back to the per‑session device name. Keep
  both machines' cabling consistent for reliable matching.

---

## How it works (one line)

`ControlMyMonitor.exe /SetValue "<monitor>" 60 <value>` per monitor - the app
just stores which `<value>` each monitor needs for each workspace and fires them
all on one click.
