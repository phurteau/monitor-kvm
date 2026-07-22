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

A **token-based dual theme** (true-black **dark** default, plus a soft off-white
**light** mode) is used throughout, driven by a single user-chosen **accent color**
picked from an **HSV color wheel** - the accent recolors every highlight (buttons,
active states, the primary-monitor ring, header glow) while all surfaces stay neutral.
Theme + accent persist across launches. Theme, color, help, and updates live in the
top-right **Menu**. A built-in **updater** shows a one-click banner when a new release
is available. The window is fully resizable, and **Exit** fully closes the app.

---

## The key idea: you switch *away from yourself*

This is the part everyone gets stuck on. The app controls your **monitors**, not
the other PC. And a monitor only reliably obeys DDC/CI from the PC that's
**currently on screen** (its active input). So the rule is:

> **The PC you're currently looking at is the one that tells the monitors to jump
> to another input.** You never need the *other* PC to be "detected."

The round-trip for a Personal PC (on DisplayPort) + Work PC (on HDMI) sharing two
monitors:

- **At the Personal PC:** click a button that sends the monitors to **HDMI** →
  your Work PC appears.
- **Now you're on the Work PC** (it's the active input): click a button that sends
  the monitors to **DisplayPort** → Personal comes back.

You don't detect "Personal" from the Work PC - the two shared monitors *are*
detected (they're showing HDMI), and you simply command them back to DisplayPort;
whatever PC is plugged into DisplayPort lights up on its own.

**Install the app on both PCs**, each with a way to point the monitors at the
*other* input. Monitors are matched by **serial number**, so profiles work on both.
Run the switch from the machine that's currently on screen. (If a PC is locked down
and can't run the app, use the monitor's physical Input button as a fallback.)

There's a **"How it works"** button (in the **Menu**) that explains this too.

---

## Fastest setup: the guided wizard

Click **Set Up Switching** on the main window. For each monitor it tries every
possible input one at a time - **just watch the monitor** and click
**"Yes - it switched!"** when it flips to the other computer, or **"No - try
next."** When you confirm, it saves your **Personal** and **Work** workspaces
automatically, and the big **SWITCH** buttons then flip your monitors with one
click. (This works even for monitors that use non‑standard input codes.)

If a monitor never switches on any code, that monitor doesn't support input
switching over DDC/CI - use its physical Input button for that one.

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
- **Pillow** (`pip install pillow`) - renders the HSV accent color wheel and tray icon
- **Optional:** `pip install pystray` - enables the system-tray icon
  (the app runs fine without it, just without a tray).
- Two (or more) source machines physically connected to the monitors at the same
  time (that's what makes it a KVM - you flip which input is shown).
- **DDC/CI must be enabled** in each monitor's on‑screen menu (it usually is by
  default; look under *Settings / Others / OSD*).
- `tools\ControlMyMonitor.exe` (NirSoft) - bundled here; it's the reliable
  Windows DDC/CI backend.

---

## First‑time setup (do this once, on the rig with the monitors)

The easy way - let the app figure out your input codes for you:

1. **Launch the app**: run the downloaded **`MonitorWorkspaceSwitcher.exe`** (or from
   source, double‑click **`Monitor Switcher.cmd`** / run `python app.py`).
2. Click **Set Up Switching**. For each monitor it tries every possible input one at
   a time - **watch the monitor** and click **"Yes - it switched!"** when it flips to
   your other computer, or **"No - try next."**
3. When you confirm, it saves your **Personal** and **Work** workspaces automatically.
   The big **SWITCH** buttons on the main window then flip your monitors with one click.

Prefer to build workspaces by hand? Click **Edit Workspaces** instead:

- **Capture** - saves the input the monitors are on *right now* (use it on the machine
  you're sitting at, e.g. capture **`Personal`** while on Personal).
- **New workspace → choose target input…** - pick the input to switch *to*, to build
  the "go to the other PC" profile you can't capture.
- Use **Test** / **Scan** on a monitor to confirm which input code actually works.

### Leaving some monitors alone

A workspace doesn't have to touch every monitor. In **Edit Workspaces**, each
monitor has an input dropdown that includes **"Leave unchanged (do nothing)"** -
pick that for any monitor you *don't* want this workspace to switch. For example,
if only two of your three monitors are shared between the two PCs, set the third to
**Leave unchanged** so it's never touched when you flip workspaces.

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

## Switch from the system tray

If `pystray` + `pillow` are installed, a green monitor icon appears in the tray while
the app is open. **Right-click it** for a menu of your workspaces - click one to flip
all monitors instantly, or use **Open Switcher** / **Quit**. **Closing the window (or
clicking Exit) fully closes the app** and ends the process - nothing is left running
in the background.

## Set an input by clicking the map

On the layout map, **click any monitor box** to open a small inline panel where you
can pick an input (from the vendor reference list) and hit **Set input** to switch it
live, or **Test** to try values without closing. This doubles as the "learn" flow:
if a value lands on the wrong source, just try another.

## Updates

On launch (and via **Menu → Check for updates**), the app asks GitHub whether a newer
release of `phurteau/monitor-kvm` exists. If so, a **green banner** appears at the
top: click **Download & Update** to fetch the release, apply it in place (your
`profiles.json` is preserved), then **Restart now** to finish. Uses only the Python
standard library - no extra dependency.

The update source is set in `version.py` (`GITHUB_OWNER` / `GITHUB_REPO`), and the
current app version is `VERSION` there - bump it and tag each GitHub release `vX.Y.Z`.

## Theming

The whole UI is driven by a small set of **design tokens** (`theme.py`) - the desktop
equivalent of CSS custom properties. There are two themes:

- **Dark** (default) - true-black background with neutral‑gray panels.
- **Light** - soft off‑white.

A single user‑chosen **accent color** drives every interactive highlight (buttons,
active states, the primary‑monitor ring, the header glow). Everything else stays
neutral, so any accent looks good. From the accent, the engine derives a brighter
companion (`acc2`, for hovers/glows) and an ink color (auto black/white) that keeps
text readable on accent fills.

Both live in the top-right **Menu**:

- **Toggle Light / Dark**.
- **Accent color…** - opens an **HSV color wheel**: drag around the wheel (hue = angle,
  saturation = distance from center), use the **Brightness** slider, or type a `#rrggbb`
  hex. Changes apply live; **Reset to default** restores the default accent (`#025500`).

Your theme + accent are saved to `settings.json` (gitignored) and restored on launch.

---

## Uninstalling

The app is portable - there's no Windows installer, so it never writes an
"install" registry entry. To remove it completely, use either:

- **In the app:** **Menu → Uninstall…** - shows exactly what will be removed, then
  clears it and closes the app.
- **Standalone:** run **`Uninstall.exe`** (included in the `-windows.zip` folder
  build), or from source `python uninstall.py` (add `--yes` to skip the prompt).

It removes everything the app creates:

- Your settings & workspaces in `%APPDATA%\MonitorWorkspaceSwitcher\`
  (`profiles.json`, `settings.json`, `switch.log`).
- Desktop shortcuts it made (`Monitors - *.lnk`, `Monitor Switcher (Setup).lnk`).
- Any startup registry value pointing at the app (defensive - the app doesn't add
  one, but a manually-added `HKCU\...\Run` entry is cleaned if found).
- The app's own folder (the folder build deletes itself right after it closes).

Unrelated files are never touched. Nothing else is left behind.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | GUI: display-layout map, click-to-set inputs, workspace buttons, capture & edit |
| `theme.py` | Token-based dual-theme engine (dark/light + accent derivation + persistence) |
| `colorwheel.py` | HSV color-wheel accent picker dialog |
| `layout.py` | Reads the live Windows display arrangement (position, size, orientation, primary) via Win32 |
| `tray.py` | Optional system-tray icon for switching workspaces without the window |
| `updater.py` | Checks GitHub Releases and applies one-click updates in place |
| `uninstall.py` | Fully removes app data, shortcuts, registry entries, and the app folder |
| `version.py` | Current `VERSION` and the GitHub repo the updater checks |
| `switch.py` | Headless one‑click apply of a named workspace |
| `make_shortcuts.py` | Generates desktop shortcuts per workspace |
| `ddc.py` | DDC/CI backend (wraps ControlMyMonitor.exe) |
| `vcp_inputs.py` | Reference table of input‑source values across vendors |
| `profiles.py` | Load/save `profiles.json` |
| `assets\make_icon.py` | Generates the app icon (`icon.ico` + PNGs) |
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
