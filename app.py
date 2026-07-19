"""
Monitor Workspace Switcher -- a software KVM for monitor inputs.

One click flips every monitor's active input (DisplayPort / HDMI / etc.) via
DDC/CI, so the same set of screens can jump between, e.g., a Personal PC on
DisplayPort and a Work PC on HDMI.

Backend: ControlMyMonitor.exe (DDC/CI, VCP feature 0x60 "Input Source").
GUI: tkinter (stdlib, no external deps).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import ddc
import layout
import profiles
import theme as theme_mod
import tray as tray_mod
import updater
from colorwheel import AccentPicker
from theme import THEME as T
from version import VERSION
from vcp_inputs import COMMON_INPUTS, FRIENDLY_INPUTS, SCAN_CANDIDATES, SKIP_INPUT, SKIP_LABEL, input_menu, label_for_value, friendly_label_for_value

APP_TITLE = "Monitor Workspace Switcher"

# Quick-switch buttons: send ALL detected monitors to a standard input value.
# These are the MCCS-standard VCP 0x60 values that work on most monitors
# (Dell, HP, ASUS, AOC, Acer, Philips, ...). Non-standard panels (some LG /
# Samsung) can use a saved workspace with per-monitor values instead.
QUICK_INPUTS = [
    ("DisplayPort", 0x0F),
    ("HDMI 1", 0x11),
    ("HDMI 2", 0x12),
    ("USB-C", 0x1B),
]


def _make_input_combo(parent, current_value=None, width=32, include_skip=False):
    """Create a readonly input-picker combobox with clean names.

    Returns (combo, get_value) where get_value() -> int|None. Value lookup goes
    through a dict (no hex parsing of labels), so it can't misfire. When
    include_skip is True, a "Leave unchanged (do nothing)" entry is offered and
    get_value() returns SKIP_INPUT for it.
    """
    display, mapping = input_menu(include_skip=include_skip)
    var = tk.StringVar()
    combo = ttk.Combobox(parent, textvariable=var, width=width, state="readonly", values=display)

    preset = None
    if current_value is not None:
        if current_value == SKIP_INPUT:
            preset = SKIP_LABEL
        else:
            for label, val in FRIENDLY_INPUTS:
                if val == current_value:
                    preset = label
                    break
            if preset is None:
                for label, val in mapping.items():
                    if val == current_value:
                        preset = label
                        break
    combo.set(preset if preset else display[0])

    def get_value():
        return mapping.get(var.get())

    return combo, get_value


def C(key):
    """Current value of a theme token (re-read live on every use)."""
    return T.t(key)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  v{VERSION}")
        self.configure(bg=C("bg"))
        self.geometry("760x820")
        self.minsize(680, 680)

        self.store = profiles.load()
        self.detected: list[ddc.Monitor] = []
        self._layout_cache: list = []
        self._ui_queue: queue.Queue = queue.Queue()
        self._themed: list = []  # (widget, {option: token_key}) for live retheme

        self._build_style()
        self._build_ui()
        self._refresh_workspace_buttons()
        self._log("Ready. Reading your display layout…")
        T.subscribe(self._apply_theme)
        self.after(80, self._pump)
        self.after(200, self.refresh_layout)
        self.after(1500, lambda: self.check_updates(manual=False))

        # system tray (optional). Closing the window (X) QUITS the app fully so
        # the process exits and the .exe file is released - no lingering
        # background process. The tray is a convenience while the app is open.
        self.tray = tray_mod.Tray(self)
        if self.tray.start():
            self._log("System tray active - right-click the tray icon to switch workspaces.")
        else:
            self._log("System tray unavailable (pystray not installed) - window mode only.")
        self.protocol("WM_DELETE_WINDOW", self._quit_app)

    # ---------- thread-safe UI marshalling ----------
    def _post(self, fn):
        """Queue a callable to run on the Tk main thread (safe from workers)."""
        self._ui_queue.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
        except queue.Empty:
            pass
        self.after(80, self._pump)

    # ---------- styling ----------
    def _track(self, widget, mapping):
        """Register a raw-tk widget so _apply_theme recolors it live.

        mapping: {tk_option: token_key}, e.g. {"bg": "panel", "fg": "txt"}.
        """
        self._themed.append((widget, mapping))
        self._apply_one(widget, mapping)
        return widget

    @staticmethod
    def _apply_one(widget, mapping):
        for opt, key in mapping.items():
            try:
                widget.configure(**{opt: C(key)})
            except tk.TclError:
                pass

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self._style = style
        self._configure_ttk()

    def _configure_ttk(self):
        style = self._style
        bg, bg2 = C("bg"), C("bg2")
        panel, panel2 = C("panel"), C("panel2")
        line, txt, dim = C("line"), C("txt"), C("dim")
        acc, acc2, ink = C("acc"), C("acc2"), C("acc_ink")

        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=txt, font=("Segoe UI", 10))
        style.configure("H1.TLabel", background=bg, foreground=acc, font=("Segoe UI Semibold", 16))
        style.configure("Muted.TLabel", background=bg, foreground=dim, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=panel, foreground=txt, font=("Segoe UI", 10))
        # neutral buttons: panel2 fill, --line border, hover raises border to --acc2
        style.configure("TButton", font=("Segoe UI", 10), padding=6,
                        background=panel2, foreground=txt, bordercolor=line,
                        focuscolor=acc2, relief="flat")
        style.map("TButton",
                  background=[("active", panel2)],
                  foreground=[("active", txt)],
                  bordercolor=[("active", acc2)])
        # accent (primary) button style
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=6,
                        background=acc, foreground=ink, bordercolor=acc, relief="flat")
        style.map("Accent.TButton",
                  background=[("active", acc2)], foreground=[("active", ink)])
        style.configure("Big.TButton", font=("Segoe UI Semibold", 12), padding=12)
        # notebook + treeview
        style.configure("TNotebook", background=bg, bordercolor=line)
        style.configure("TNotebook.Tab", background=panel, foreground=txt, padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", panel2)],
                  foreground=[("selected", acc)])
        style.configure("Treeview", background=panel, fieldbackground=panel, foreground=txt,
                        bordercolor=line)
        style.configure("Treeview.Heading", background=bg, foreground=acc)
        style.map("Treeview", background=[("selected", acc)], foreground=[("selected", ink)])
        style.configure("TCombobox", fieldbackground=panel2, background=panel2, foreground=txt)
        style.configure("Vertical.TScrollbar", background=panel2, troughcolor=bg,
                        bordercolor=line, arrowcolor=dim)

    def _apply_theme(self):
        """Re-apply all colors after a theme/accent change (live)."""
        self.configure(bg=C("bg"))
        self._configure_ttk()
        for widget, mapping in list(self._themed):
            try:
                if widget.winfo_exists():
                    self._apply_one(widget, mapping)
                else:
                    self._themed.remove((widget, mapping))
            except tk.TclError:
                pass
        self._draw_header()
        self._refresh_workspace_buttons()
        self._draw_layout()
        if getattr(self, "_banner_info", None) is not None:
            self._style_banner()
        tobj = getattr(self, "tray", None)
        if tobj is not None:
            try:
                tobj.refresh_icon()
            except Exception:  # noqa: BLE001
                pass

    # ---------- main layout ----------
    def _build_ui(self):
        # header: canvas with gradient + faint accent radial glow + title
        self.header = tk.Canvas(self, height=76, highlightthickness=0, bd=0)
        self._track(self.header, {"bg": "head2"})
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._draw_header())

        # theme controls row (top-right of the header area)
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=18, pady=(6, 0))
        ttk.Button(ctrl, text="Toggle Light/Dark", command=self._toggle_theme).pack(side="right")
        ttk.Button(ctrl, text="Color", command=self._open_accent_picker).pack(side="right", padx=(0, 6))

        # update banner (hidden until an update is found)
        self.banner = tk.Frame(self, highlightthickness=1)
        self.banner_label = tk.Label(self.banner, text="", font=("Segoe UI Semibold", 10),
                                     anchor="w", justify="left")
        self.banner_label.pack(side="left", padx=12, pady=8)
        self.banner_btn = tk.Button(self.banner, text="Download & Update", relief="flat",
                                    font=("Segoe UI Semibold", 10), padx=14, pady=5,
                                    cursor="hand2", bd=0)
        self.banner_btn.pack(side="right", padx=(6, 12), pady=8)
        self.banner_dismiss = tk.Button(self.banner, text="Dismiss", relief="flat",
                                        font=("Segoe UI", 9), padx=8, pady=5,
                                        cursor="hand2", bd=0, command=self._hide_banner)
        self.banner_dismiss.pack(side="right", pady=8)
        self._banner_info = None
        self._style_banner()

        # live display layout map
        maphead = ttk.Frame(self)
        maphead.pack(fill="x", padx=18, pady=(12, 2))
        ttk.Label(maphead, text="DISPLAY LAYOUT", style="Muted.TLabel").pack(side="left")
        ttk.Button(maphead, text="Refresh", command=self.refresh_layout).pack(side="right")
        self.canvas = tk.Canvas(self, height=210, highlightthickness=0, bd=0)
        self._track(self.canvas, {"bg": "panel"})
        self.canvas.pack(fill="x", padx=18)
        self.canvas.bind("<Configure>", lambda e: self._draw_layout())
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # quick switch: send ALL detected monitors to a standard input in one click
        ttk.Label(self, text="QUICK SWITCH  (send all monitors to one input)",
                  style="Muted.TLabel").pack(anchor="w", padx=18, pady=(12, 2))
        qrow = ttk.Frame(self)
        qrow.pack(fill="x", padx=18)
        for label, value in QUICK_INPUTS:
            b = tk.Button(
                qrow, text=f"All → {label}",
                command=lambda v=value, l=label: self.quick_switch_all(v, l),
                relief="flat", font=("Segoe UI Semibold", 10),
                padx=14, pady=8, cursor="hand2", bd=0, highlightthickness=1,
            )
            self._track(b, {"bg": "panel2", "fg": "txt", "activebackground": "panel",
                            "activeforeground": "acc", "highlightbackground": "line"})
            b.pack(side="left", padx=(0, 8))

        # workspace buttons area
        ttk.Label(self, text="WORKSPACES", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(12, 2))
        self.ws_frame = ttk.Frame(self)
        self.ws_frame.pack(fill="x", padx=18)

        # toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        ttk.Button(bar, text="Detect Monitors", command=self.detect_monitors).pack(side="left")
        ttk.Button(bar, text="Set up switching", command=self.start_guided_setup, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(bar, text="Setup / Edit Workspaces", command=self.open_setup).pack(side="left")
        ttk.Button(bar, text="How it works", command=self._show_how_it_works).pack(side="left", padx=6)
        ttk.Button(bar, text="Check for Updates", command=lambda: self.check_updates(manual=True)).pack(side="right")
        ttk.Button(bar, text="Quit", command=self._quit_app).pack(side="right", padx=(0, 6))

        # log
        ttk.Label(self, text="ACTIVITY", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(6, 2))
        logwrap = ttk.Frame(self)
        logwrap.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.log = tk.Text(logwrap, height=10, relief="flat", font=("Cascadia Mono", 9), wrap="word")
        self._track(self.log, {"bg": "panel", "fg": "txt", "insertbackground": "txt"})
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logwrap, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        self._draw_header()

    # ---------- header gradient + accent glow ----------
    def _draw_header(self):
        c = self.header
        if not c.winfo_exists():
            return
        c.delete("all")
        w = c.winfo_width() or 760
        h = int(c["height"])
        # horizontal gradient head1 -> head2, drawn as gapless 2px bands
        h1 = theme_mod.hex_to_rgb(C("head1"))
        h2 = theme_mod.hex_to_rgb(C("head2"))
        band = 2
        for x in range(0, w, band):
            f = x / max(1, w - 1)
            r = int(h1[0] + (h2[0] - h1[0]) * f)
            g = int(h1[1] + (h2[1] - h1[1]) * f)
            b = int(h1[2] + (h2[2] - h1[2]) * f)
            c.create_rectangle(x, 0, x + band, h, outline="",
                               fill=theme_mod.rgb_to_hex(r, g, b))
        # faint accent radial glow near top-center (layered ovals over the gradient)
        acc = theme_mod.hex_to_rgb(C("acc2"))
        base = theme_mod.hex_to_rgb(C("head1"))
        cx = w // 2
        for i, frac in enumerate([0.06, 0.11, 0.17]):
            rad = 260 - i * 70
            col = tuple(int(base[k] + (acc[k] - base[k]) * frac) for k in range(3))
            c.create_oval(cx - rad, -rad + 8, cx + rad, rad // 2 + 8,
                          outline="", fill=theme_mod.rgb_to_hex(*col))
        # readable text: keep the accent "pop" when it passes AA contrast on this
        # header background, otherwise fall back to neutral high-contrast text.
        head_bg = C("head1")
        acc_variants = [C("acc"), C("acc2")]
        best_acc = max(acc_variants, key=lambda cc: theme_mod.contrast(cc, head_bg))
        title_col = best_acc if theme_mod.contrast(best_acc, head_bg) >= 4.5 else C("txt")
        sub_col = theme_mod.best_on(head_bg, [C("txt"), C("dim")])
        c.create_text(20, h // 2 - 8, anchor="w", text="Monitor Workspace Switcher",
                      fill=title_col, font=("Segoe UI Semibold", 16))
        c.create_text(22, h // 2 + 16, anchor="w",
                      text=f"One click flips your monitors between inputs (a software KVM).  v{VERSION}",
                      fill=sub_col, font=("Segoe UI", 9))

    # ---------- theme controls ----------
    def _toggle_theme(self):
        T.toggle_theme()
        self._log(f"Theme: {T.name}.")

    def _open_accent_picker(self):
        AccentPicker(self, T, on_change=lambda hexv: T.set_accent(hexv))

    def _style_banner(self):
        acc, ink, dim, txt = C("acc"), C("acc_ink"), C("dim"), C("txt")
        panel2 = C("panel2")
        self.banner.configure(bg=panel2, highlightbackground=acc, highlightcolor=acc)
        self.banner_label.configure(bg=panel2, fg=acc)
        self.banner_btn.configure(bg=acc, fg=ink, activebackground=C("acc2"), activeforeground=ink)
        self.banner_dismiss.configure(bg=panel2, fg=dim, activebackground=C("panel"),
                                      activeforeground=txt)

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- workspace buttons ----------
    def _refresh_workspace_buttons(self):
        for w in self.ws_frame.winfo_children():
            w.destroy()
        if not self.store.workspaces:
            ttk.Label(self.ws_frame,
                      text="No workspaces yet. Click 'Setup / Edit Workspaces' to create one.",
                      style="Muted.TLabel").pack(anchor="w", pady=6)
            return
        row = ttk.Frame(self.ws_frame)
        row.pack(fill="x", pady=4)
        for i, ws in enumerate(self.store.workspaces):
            b = tk.Button(
                row, text=ws.name, command=lambda w=ws: self.apply_workspace(w),
                bg=C("acc"), fg=C("acc_ink"), activebackground=C("acc2"),
                activeforeground=C("acc_ink"),
                relief="flat", font=("Segoe UI Semibold", 13), padx=22, pady=16, cursor="hand2",
                bd=0, highlightthickness=0,
            )
            b.pack(side="left", padx=(0, 10))
        # keep the tray menu in sync with the current workspaces
        t = getattr(self, "tray", None)
        if t is not None:
            t.update_menu()

    # ---------- tray / window helpers ----------
    def apply_workspace_by_name(self, name: str):
        ws = self.store.get(name)
        if ws:
            self.apply_workspace(ws)

    # ---------- quick switch (all monitors -> one input) ----------
    def quick_switch_all(self, value: int, label: str):
        def work():
            live = self.detected or ddc.list_monitors()
            controllable = [m for m in live]
            if not controllable:
                self._post(lambda: self._log("Quick switch: no monitors detected."))
                return
            self._post(lambda: self._log(f"Quick switch: sending all monitors → {label} (0x{value:02X})…"))
            applied = ignored = fail = 0
            for m in controllable:
                try:
                    ok, readback = ddc.set_input_source_verified(m, value)
                    if ok:
                        applied += 1
                        self._post(lambda m=m: self._log(f"  \u2713 {m.display_label} → {label} (confirmed)"))
                    elif readback is None:
                        applied += 1  # can't verify (monitor dropped DDC on the old input) - assume sent
                        self._post(lambda m=m: self._log(f"  \u2713 {m.display_label} → {label} (sent; couldn't read back to confirm)"))
                    else:
                        ignored += 1
                        rb = f"0x{readback:02X}"
                        self._post(lambda m=m, rb=rb: self._log(
                            f"  \u26a0 {m.display_label}: sent {label} but monitor still reports {rb} - "
                            f"it ignored this code (wrong value for this monitor, or that input has no signal)."))
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    self._post(lambda e=e, m=m: self._log(f"  ! {m.name or m.stable_id}: {e}"))
            summary = f"Quick switch done: {applied} confirmed"
            if ignored:
                summary += f", {ignored} not applied"
            if fail:
                summary += f", {fail} failed"
            self._post(lambda: self._log(summary + "."))
            if ignored and not applied:
                self._post(lambda: self._log(
                    "Tip: if the OTHER PC is off/asleep, turn it on first (monitors won't switch to a dead input). "
                    "Otherwise your monitor may use a non-standard code - use Setup → Workspaces → Test to find the one that works."))
            self._post(self.refresh_layout)
        threading.Thread(target=work, daemon=True).start()

    # ---------- how it works ----------
    def _show_how_it_works(self):
        panel, txt, acc, dim, line = C("panel"), C("txt"), C("acc"), C("dim"), C("line")
        top = tk.Toplevel(self)
        top.title("How it works")
        top.configure(bg=panel)
        top.transient(self)
        top.geometry("560x430")
        top.resizable(False, False)

        tk.Label(top, text="How a software KVM switches your monitors", bg=panel, fg=acc,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=16, pady=(14, 6))

        body = (
            "This app controls your MONITORS over DDC/CI (the same channel their\n"
            "on-screen menu uses) - it does not control the other PC.\n\n"
            "The golden rule:\n"
            "    You switch AWAY from the PC you're currently looking at.\n\n"
            "A monitor reliably obeys DDC/CI only from the PC that's currently on\n"
            "screen (its active input). So:\n\n"
            "  •  At your Personal PC (monitors on DisplayPort): click a button\n"
            "     that sends the monitors to HDMI → your Work PC appears.\n\n"
            "  •  Now you're on the Work PC (it's the active input): click a button\n"
            "     that sends the monitors to DisplayPort → Personal comes back.\n\n"
            "You never need the other PC to be 'detected'. The monitors are what's\n"
            "detected; you just tell them which input to jump to, and whatever PC is\n"
            "plugged into that input lights up on its own.\n\n"
            "Setup: install this app on BOTH PCs. On each, make a profile (or use the\n"
            "Quick Switch buttons) that points the monitors at the OTHER input.\n"
            "Monitors are matched by serial number, so profiles work on both PCs.\n\n"
            "Note: run the switch from the machine that's currently on screen. If a\n"
            "PC is locked down and can't run the app, use the monitor's physical\n"
            "Input button as a fallback."
        )
        tk.Label(top, text=body, bg=panel, fg=txt, font=("Segoe UI", 9), justify="left").pack(
            anchor="w", padx=16)
        tk.Button(top, text="Got it", command=top.destroy, bg=acc, fg=C("acc_ink"),
                  activebackground=C("acc2"), activeforeground=C("acc_ink"), relief="flat",
                  font=("Segoe UI Semibold", 10), padx=16, pady=6, cursor="hand2", bd=0).pack(
            anchor="e", padx=16, pady=12)

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))

    def _hide_to_tray(self):
        self.withdraw()

    def _quit_app(self):
        # Stop the tray icon (runs on its own thread), tear down Tk, then force
        # the process to exit so no background thread keeps the .exe locked.
        t = getattr(self, "tray", None)
        if t is not None:
            try:
                t.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.quit()       # break out of mainloop
        except Exception:  # noqa: BLE001
            pass
        try:
            self.destroy()    # tear down all Tk windows
        except Exception:  # noqa: BLE001
            pass
        # Guaranteed termination - pystray/other daemon threads can otherwise
        # keep the frozen exe's process alive (and the file locked).
        import os
        os._exit(0)

    # ---------- updater ----------
    def check_updates(self, manual: bool = False):
        def work():
            info = updater.check_for_update()
            if info.available:
                self._post(lambda: self._show_banner(info))
                self._post(lambda: self._log(f"Update available: v{info.current} -> v{info.latest}."))
            elif manual:
                if info.error:
                    self._post(lambda: self._log(f"Update check: {info.error}"))
                else:
                    self._post(lambda: self._log(f"You're up to date (v{info.current})."))
        threading.Thread(target=work, daemon=True).start()

    def _show_banner(self, info):
        self._banner_info = info
        self._style_banner()
        notes = f"  -  {info.notes.splitlines()[0]}" if info.notes else ""
        self.banner_label.config(text=f"Update available:  v{info.current}  \u2192  v{info.latest}{notes}")
        self.banner_btn.config(text="Download & Update", state="normal",
                               command=lambda: self._do_update(info))
        # place the banner near the top, above the layout map
        self.banner.pack(fill="x", padx=18, pady=(4, 6), after=self.header)

    def _hide_banner(self):
        try:
            self.banner.pack_forget()
        except tk.TclError:
            pass

    def _do_update(self, info):
        self.banner_btn.config(text="Updating…", state="disabled")
        self._log(f"Downloading update v{info.latest}…")

        def work():
            ok, msg = updater.download_and_apply(info.download_url)
            self._post(lambda: self._log(msg))
            if ok:
                self._post(self._offer_restart)
            else:
                self._post(lambda: self.banner_btn.config(text="Retry Update", state="normal"))
        threading.Thread(target=work, daemon=True).start()

    def _offer_restart(self):
        self.banner_label.config(text="Update installed. Restart to apply.")
        self.banner_btn.config(text="Restart now", state="normal", command=self._restart_app)

    def _restart_app(self):
        import sys
        import os
        import subprocess
        try:
            if getattr(sys, "frozen", False):
                # packaged exe: relaunch the exe itself
                subprocess.Popen([sys.executable], cwd=os.path.dirname(sys.executable))
            else:
                script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
                py = sys.executable
                pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
                launcher = pyw if os.path.exists(pyw) else py
                subprocess.Popen([launcher, script], cwd=os.path.dirname(script))
        except Exception as e:  # noqa: BLE001
            self._log(f"Restart failed, please relaunch manually: {e}")
            return
        self._quit_app()

    # ---------- actions ----------
    def detect_monitors(self):
        def work():
            try:
                mons = ddc.list_monitors()
            except ddc.DDCError as e:
                self._post( lambda: self._log(f"ERROR: {e}"))
                return
            self.detected = mons
            if not mons:
                self._post( lambda: self._log("No monitors detected. Connect displays and ensure DDC/CI is ON in each monitor's OSD menu."))
                return
            lines = ["Detected monitors:"]
            for m in mons:
                cur = ddc.get_input_source(m)
                cur_txt = f"0x{cur:02X} ({label_for_value(cur)})" if cur is not None else "unreadable"
                lines.append(f"  [{m.index}] {m.display_label}")
                lines.append(f"        current input: {cur_txt}")
            self._post( lambda: self._log("\n".join(lines)))
        threading.Thread(target=work, daemon=True).start()
        self._log("Detecting monitors…")

    def self_test(self):
        def work():
            out = ddc.self_test()
            self._post( lambda: self._log("Self-test:\n" + out))
        threading.Thread(target=work, daemon=True).start()

    def apply_workspace(self, ws: profiles.Workspace):
        def work():
            self._post( lambda: self._log(f"Applying workspace '{ws.name}'…"))
            live = {m.stable_id: m for m in (self.detected or ddc.list_monitors())}
            ok, miss, left, ignored = 0, 0, 0, 0
            for a in ws.assignments:
                if a.value == SKIP_INPUT:
                    left += 1
                    self._post( lambda a=a: self._log(f"  \u2013 {a.monitor_label}: left unchanged"))
                    continue
                m = live.get(a.monitor_id)
                if not m:
                    # try to match by index fallback
                    miss += 1
                    self._post( lambda a=a: self._log(f"  ! monitor '{a.monitor_label}' ({a.monitor_id}) not currently attached - skipped"))
                    continue
                try:
                    applied_ok, readback = ddc.set_input_source_verified(m, a.value)
                    label = a.value_label or label_for_value(a.value)
                    if applied_ok:
                        ok += 1
                        self._post( lambda a=a, label=label: self._log(f"  \u2713 {a.monitor_label} -> {label} (0x{a.value:02X}) confirmed"))
                    elif readback is None:
                        ok += 1  # couldn't read back (monitor dropped DDC on old input) - assume sent
                        self._post( lambda a=a, label=label: self._log(f"  \u2713 {a.monitor_label} -> {label} (sent; couldn't read back to confirm)"))
                    else:
                        ignored += 1
                        rb = f"0x{readback:02X}"
                        self._post( lambda a=a, label=label, rb=rb: self._log(
                            f"  \u26a0 {a.monitor_label}: sent {label} but still reports {rb} - code ignored."))
                except Exception as e:
                    miss += 1
                    self._post( lambda e=e, a=a: self._log(f"  ! {a.monitor_label}: {e}"))
            summary = f"Done: {ok} confirmed"
            if ignored:
                summary += f", {ignored} not applied"
            if miss:
                summary += f", {miss} skipped"
            if left:
                summary += f", {left} left unchanged"
            self._post( lambda: self._log(summary + "."))
            if ignored and not ok:
                self._post( lambda: self._log(
                    "Tip: turn the target PC on first (monitors won't switch to a dead input), or the code is wrong - "
                    "use Setup → Workspaces → Test to find the input value that actually switches."))
            self._post(self.refresh_layout)
        threading.Thread(target=work, daemon=True).start()

    # ---------- setup window ----------
    def open_setup(self):
        SetupWindow(self)

    # ---------- live layout map ----------
    def refresh_layout(self):
        def work():
            try:
                displays = layout.get_displays()
            except Exception as e:  # noqa: BLE001
                self._post( lambda e=e: self._log(f"Layout read error: {e}"))
                displays = []
            try:
                mons = ddc.list_monitors()
            except ddc.DDCError:
                mons = []
            self.detected = mons

            items = []
            for d in displays:
                m = self._match_monitor(d, mons)
                cur = ddc.get_input_source(m) if m else None
                items.append({"display": d, "monitor": m, "input": cur})
            self._layout_cache = items
            self._post( self._draw_layout)
            n = len(displays)
            self._post( lambda n=n: self._log(f"Layout: {n} display(s) read from Windows."))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _match_monitor(d, monitors):
        token = (d.device_name or "").upper()
        for m in monitors:
            if m.device_name and m.device_name.upper().startswith(token + "\\"):
                return m
        for m in monitors:
            if m.monitor_id and d.monitor_id and m.monitor_id.upper() == d.monitor_id.upper():
                return m
        return None

    def _draw_layout(self):
        c = self.canvas
        c.delete("all")
        self._layout_rects = []
        items = self._layout_cache
        cw = c.winfo_width() or 700
        ch = c.winfo_height() or 210
        if not items:
            c.create_text(cw // 2, ch // 2, text="No displays read yet - click Refresh",
                          fill=C("dim"), font=("Segoe UI", 10))
            return

        pad = 16
        minx = min(it["display"].x for it in items)
        miny = min(it["display"].y for it in items)
        maxx = max(it["display"].x + it["display"].width for it in items)
        maxy = max(it["display"].y + it["display"].height for it in items)
        span_w = max(1, maxx - minx)
        span_h = max(1, maxy - miny)
        scale = min((cw - 2 * pad) / span_w, (ch - 2 * pad) / span_h)
        draw_w = span_w * scale
        draw_h = span_h * scale
        ox = (cw - draw_w) / 2
        oy = (ch - draw_h) / 2

        for it in items:
            d = it["display"]
            m = it["monitor"]
            x0 = ox + (d.x - minx) * scale
            y0 = oy + (d.y - miny) * scale
            x1 = x0 + d.width * scale
            y1 = y0 + d.height * scale

            controllable = m is not None
            fill = C("panel2") if controllable else C("bg2")
            border = C("acc") if d.primary else (C("line") if controllable else C("line"))
            rid = c.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3,
                                     fill=fill, outline=border, width=2)
            # remember hit-box -> item (only DDC-controllable ones are clickable)
            self._layout_rects.append((x0 + 3, y0 + 3, x1 - 3, y1 - 3, it))
            if controllable:
                c.tag_bind(rid, "<Enter>", lambda e: c.config(cursor="hand2"))
                c.tag_bind(rid, "<Leave>", lambda e: c.config(cursor=""))

            if m is None:
                inp = "no DDC control"
            elif it["input"] is None:
                inp = "input: n/a"
            else:
                inp = f"{label_for_value(it['input']).split(' (')[0]}"

            name = d.friendly or d.device_name.replace("\\\\.\\", "")
            if len(name) > 20:
                name = name[:19] + "\u2026"
            res = f"{d.width}\u00d7{d.height}"
            orient = "Portrait" if d.is_portrait else "Landscape"
            prim = "  \u2605" if d.primary else ""
            hint = "click to set" if controllable else ""

            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            lines = [name + prim, res, orient, inp, hint]
            line_h = 14
            start = cy - (len(lines) - 1) * line_h / 2
            in_color = C("acc") if (m and it["input"] is not None) else C("dim")
            colors = [C("txt"), C("dim"), C("dim"), in_color, C("dim")]
            for i, (ln, col) in enumerate(zip(lines, colors)):
                if not ln:
                    continue
                c.create_text(cx, start + i * line_h, text=ln, fill=col,
                              font=("Segoe UI", 8) if i else ("Segoe UI Semibold", 9))

    def _on_canvas_click(self, event):
        for x0, y0, x1, y1, it in getattr(self, "_layout_rects", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if it["monitor"] is None:
                    self._log("That display isn't DDC/CI-controllable (no monitor match).")
                    return
                self._open_input_popup(it, event.x_root, event.y_root)
                return

    def _open_input_popup(self, it, sx, sy):
        m = it["monitor"]
        panel, panel2, txt, dim = C("panel"), C("panel2"), C("txt"), C("dim")
        acc, acc2, ink, line = C("acc"), C("acc2"), C("acc_ink"), C("line")
        top = tk.Toplevel(self)
        top.title("Set input")
        top.configure(bg=panel)
        top.transient(self)
        top.geometry(f"+{sx}+{sy}")
        top.attributes("-topmost", True)

        d = it["display"]
        tk.Label(top, text=d.friendly or m.display_label, bg=panel, fg=acc,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=12, pady=(10, 2))
        cur = it["input"]
        cur_txt = label_for_value(cur) if cur is not None else "unknown"
        tk.Label(top, text=f"Current input: {cur_txt}", bg=panel, fg=dim,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        combo, get_value = _make_input_combo(top, current_value=cur, width=34)
        combo.pack(padx=12, pady=10)

        tk.Label(top, text="Setting an input may switch this monitor to another\nmachine - use its physical buttons to return if needed.",
                 bg=panel, fg=dim, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=12)

        btns = tk.Frame(top, bg=panel)
        btns.pack(fill="x", padx=12, pady=10)

        def do_set(close=True):
            val = get_value()
            if val is None:
                return
            def work():
                try:
                    ddc.set_input_source(m, val)
                    self._post(lambda: self._log(f"Set {d.friendly or m.stable_id} -> 0x{val:02X} ({friendly_label_for_value(val)})"))
                    self._post(self.refresh_layout)
                except Exception as e:  # noqa: BLE001
                    self._post(lambda e=e: self._log(f"Set failed: {e}"))
            threading.Thread(target=work, daemon=True).start()
            if close:
                top.destroy()

        tk.Button(btns, text="Set input", command=lambda: do_set(True),
                  bg=acc, fg=ink, activebackground=acc2, activeforeground=ink,
                  relief="flat", font=("Segoe UI Semibold", 10), padx=14, pady=6,
                  cursor="hand2", bd=0).pack(side="left")
        tk.Button(btns, text="Test", command=lambda: do_set(False),
                  bg=panel2, fg=txt, activebackground=panel, activeforeground=txt,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", highlightthickness=1, highlightbackground=line, bd=0).pack(side="left", padx=6)
        tk.Button(btns, text="Scan for codes",
                  command=lambda: (top.destroy(), self.scan_monitor(m, d.friendly or m.display_label)),
                  bg=panel2, fg=acc, activebackground=panel, activeforeground=acc,
                  relief="flat", font=("Segoe UI Semibold", 10), padx=10, pady=6,
                  cursor="hand2", highlightthickness=1, highlightbackground=line, bd=0).pack(side="left")
        tk.Button(btns, text="Close", command=top.destroy,
                  bg=panel, fg=dim, activebackground=panel2, activeforeground=txt,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", bd=0).pack(side="right")

    def scan_monitor(self, m, label):
        """Cycle a monitor through all known input codes and log which it accepts.
        Shared by the map-click popup and the Setup workspace editor."""
        if not messagebox.askyesno(
                "Scan inputs",
                f"This will briefly cycle '{label}' through every known input code to find "
                "which ones it accepts, then put it back.\n\n"
                "The screen may flicker or show 'no signal' for a few seconds. Keep the other "
                "PC powered on so its input lights up.\n\nProceed?",
                parent=self):
            return
        self._log(f"[Scan] {label}: scanning input codes… (~20s, screen may flicker)")

        def work():
            accepted = []

            def prog(v, ok, rb):
                if ok:
                    accepted.append(v)
                    self._post(lambda v=v: self._log(
                        f"    accepts: {friendly_label_for_value(v)} (0x{v:02X})"))

            try:
                original, results = ddc.scan_inputs(m, SCAN_CANDIDATES, progress=prog)
            except Exception as e:  # noqa: BLE001
                self._post(lambda e=e: self._log(f"[Scan] failed: {e}"))
                return

            def done():
                if accepted:
                    names = ", ".join(f"{friendly_label_for_value(v)} (0x{v:02X})" for v in accepted)
                    self._log(f"[Scan] {label}: this monitor accepts -> {names}")
                    self._log("       Use the code for the port your other PC is on "
                              "(click the monitor again, or Setup -> Workspaces).")
                else:
                    self._log(f"[Scan] {label}: no code confirmed. If the other PC is on, "
                              "your monitor may block DDC input-switching - check that DDC/CI "
                              "is enabled in its on-screen menu.")
            self._post(done)
        threading.Thread(target=work, daemon=True).start()

    def scan_all_monitors(self):
        """Scan every detected monitor, one after another, and report the codes
        each accepts. The most discoverable way to find your real input codes."""
        mons = self.detected or []
        if not mons:
            self._log("Find input codes: no monitors detected yet - detecting now…")
            self.detect_monitors()
            return
        if not messagebox.askyesno(
                "Find input codes",
                f"This will briefly cycle each of your {len(mons)} monitor(s) through every known "
                "input code to discover which ones they accept, then restore them.\n\n"
                "Screens may flicker or show 'no signal' for a few seconds each. Keep the other "
                "PC(s) powered on.\n\nProceed?",
                parent=self):
            return

        def work():
            for m in mons:
                label = m.name or m.display_label
                accepted = []

                def prog(v, ok, rb, accepted=accepted):
                    if ok:
                        accepted.append(v)
                        self._post(lambda v=v: self._log(
                            f"    accepts: {friendly_label_for_value(v)} (0x{v:02X})"))

                self._post(lambda label=label: self._log(f"[Scan] {label}: scanning…"))
                try:
                    ddc.scan_inputs(m, SCAN_CANDIDATES, progress=prog)
                except Exception as e:  # noqa: BLE001
                    self._post(lambda e=e, label=label: self._log(f"[Scan] {label}: failed: {e}"))
                    continue
                if accepted:
                    names = ", ".join(f"{friendly_label_for_value(v)} (0x{v:02X})" for v in accepted)
                    self._post(lambda names=names, label=label: self._log(f"[Scan] {label}: accepts -> {names}"))
                else:
                    self._post(lambda label=label: self._log(
                        f"[Scan] {label}: no code confirmed (check DDC/CI is on in its menu)."))
            self._post(lambda: self._log("Find input codes: done. Use a confirmed code in a workspace or via the map."))
            self._post(self.refresh_layout)
        threading.Thread(target=work, daemon=True).start()

    # ---------- guided switching setup ----------
    def start_guided_setup(self):
        mons = self.detected or []
        if not mons:
            self._log("Set up switching: detecting monitors first…")
            self.detect_monitors()
            self.after(1500, self.start_guided_setup)
            return
        GuidedSwitchWizard(self, mons)

    def _upsert_assignment(self, ws_name: str, monitor, value: int, value_label: str):
        """Add/update one monitor's assignment inside a named workspace (create
        the workspace if needed). Other monitors in the workspace are left as-is,
        defaulting to 'Leave unchanged' if the wizard hasn't set them."""
        ws = self.store.get(ws_name)
        if ws is None:
            ws = profiles.Workspace(name=ws_name, assignments=[])
            self.store.workspaces.append(ws)
        mid = monitor.stable_id
        for a in ws.assignments:
            if a.monitor_id == mid:
                a.value = value
                a.value_label = value_label
                a.monitor_label = monitor.name or monitor.display_label
                break
        else:
            ws.assignments.append(profiles.Assignment(
                monitor_id=mid,
                monitor_label=monitor.name or monitor.display_label,
                value=value,
                value_label=value_label,
            ))
        profiles.save(self.store)


class GuidedSwitchWizard(tk.Toplevel):
    """Interactive, eyes-not-readback wizard to find each monitor's real input
    codes and build Personal/Work workspaces automatically.

    For each shared monitor it records the CURRENT input (that's the 'this PC'
    code), then steps through every candidate code one at a time. The user just
    watches the monitor and clicks 'Yes, it switched' when it flips to the other
    computer. On confirmation the monitor is switched back, and both workspaces
    are updated: this-PC input -> current workspace, the found input -> the other.
    """

    def __init__(self, app: App, monitors):
        super().__init__(app)
        self.app = app
        self.monitors = list(monitors)
        self.title("Set up switching")
        self.configure(bg=C("panel"))
        self.geometry("560x340")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._stop)

        self._mi = 0            # monitor index
        self._candidates = []   # codes to try for current monitor
        self._ci = 0            # candidate index
        self._original = None   # current monitor's starting input
        self._busy = False
        self._found_any = False

        panel, txt, acc, dim = C("panel"), C("txt"), C("acc"), C("dim")
        self.h = tk.Label(self, text="", bg=panel, fg=acc, font=("Segoe UI Semibold", 13),
                          wraplength=520, justify="left")
        self.h.pack(anchor="w", padx=18, pady=(16, 4))
        self.body = tk.Label(self, text="", bg=panel, fg=txt, font=("Segoe UI", 10),
                             wraplength=520, justify="left")
        self.body.pack(anchor="w", padx=18)
        self.status = tk.Label(self, text="", bg=panel, fg=acc, font=("Segoe UI Semibold", 11),
                               wraplength=520, justify="left")
        self.status.pack(anchor="w", padx=18, pady=(10, 0))

        self.btns = tk.Frame(self, bg=panel)
        self.btns.pack(side="bottom", fill="x", padx=18, pady=16)
        self.yes_btn = tk.Button(self.btns, text="Yes - it switched!", command=self._on_yes,
                                 bg=acc, fg=C("acc_ink"), activebackground=C("acc2"),
                                 activeforeground=C("acc_ink"), relief="flat",
                                 font=("Segoe UI Semibold", 10), padx=14, pady=7, cursor="hand2", bd=0)
        self.no_btn = tk.Button(self.btns, text="No - try next", command=self._on_no,
                                bg=C("panel2"), fg=txt, activebackground=panel, activeforeground=txt,
                                relief="flat", font=("Segoe UI", 10), padx=12, pady=7, cursor="hand2",
                                highlightthickness=1, highlightbackground=C("line"), bd=0)
        self.skip_btn = tk.Button(self.btns, text="Skip this monitor", command=self._on_skip,
                                  bg=panel, fg=dim, activebackground=C("panel2"), activeforeground=txt,
                                  relief="flat", font=("Segoe UI", 9), padx=10, pady=7, cursor="hand2", bd=0)
        self.stop_btn = tk.Button(self.btns, text="Stop", command=self._stop,
                                  bg=panel, fg=dim, activebackground=C("panel2"), activeforeground=txt,
                                  relief="flat", font=("Segoe UI", 9), padx=10, pady=7, cursor="hand2", bd=0)
        self.yes_btn.pack(side="left")
        self.no_btn.pack(side="left", padx=6)
        self.skip_btn.pack(side="left")
        self.stop_btn.pack(side="right")

        self._start_monitor()

    def _cur_monitor(self):
        return self.monitors[self._mi]

    def _mlabel(self):
        m = self._cur_monitor()
        return m.name or m.display_label

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.yes_btn, self.no_btn, self.skip_btn):
            b.configure(state=state)

    def _start_monitor(self):
        if self._mi >= len(self.monitors):
            self._finish()
            return
        m = self._cur_monitor()
        self.h.config(text=f"Monitor {self._mi + 1} of {len(self.monitors)}:  {self._mlabel()}")
        self.body.config(text=(
            "Watch THIS monitor. I'll try each possible input one at a time.\n"
            "When it switches to your OTHER computer, click \u201cYes - it switched!\u201d.\n"
            "If nothing happens, click \u201cNo - try next\u201d."))
        self.status.config(text="Reading current input…")
        self._set_busy(True)

        def work():
            original = ddc.get_input_source(m)
            self._original = original
            cands = [c for c in SCAN_CANDIDATES if original is None or (c & 0xFF) != (original & 0xFF)]
            self._candidates = cands
            self._ci = 0
            self.app._post(self._try_current)
        threading.Thread(target=work, daemon=True).start()

    def _try_current(self):
        if self._ci >= len(self._candidates):
            self._monitor_exhausted()
            return
        m = self._cur_monitor()
        code = self._candidates[self._ci]
        name = friendly_label_for_value(code)
        self.status.config(text=f"Trying:  {name}  (0x{code:02X})   -   did the monitor switch?")
        self._set_busy(True)

        def work():
            try:
                ddc.set_input_source(m, code)
            except Exception:  # noqa: BLE001
                pass
            import time
            time.sleep(0.6)
            self.app._post(lambda: self._set_busy(False))
        threading.Thread(target=work, daemon=True).start()

    def _on_no(self):
        if self._busy:
            return
        self._ci += 1
        self._try_current()

    def _on_yes(self):
        if self._busy:
            return
        m = self._cur_monitor()
        code = self._candidates[self._ci]
        found_label = friendly_label_for_value(code)
        orig = self._original
        orig_label = friendly_label_for_value(orig) if orig is not None else "current input"
        self._found_any = True
        self._set_busy(True)
        self.status.config(text=f"Saved {self._mlabel()} → {found_label}. Switching back…")

        # Build workspaces: current input = "Personal" (this PC), found = "Work" (other PC).
        if orig is not None:
            self.app._upsert_assignment("Personal", m, orig & 0xFF, orig_label)
        self.app._upsert_assignment("Work", m, code & 0xFF, found_label)
        self.app._log(f"[Setup] {self._mlabel()}: Work = {found_label} (0x{code:02X}), "
                      f"Personal = {orig_label}" + (f" (0x{orig:02X})" if orig is not None else ""))

        def work():
            import time
            if orig is not None:
                try:
                    ddc.set_input_source(m, orig)
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.6)
            self.app._post(self._advance_monitor)
        threading.Thread(target=work, daemon=True).start()

    def _monitor_exhausted(self):
        m = self._cur_monitor()
        # restore original just in case
        orig = self._original
        if orig is not None:
            try:
                ddc.set_input_source(m, orig)
            except Exception:  # noqa: BLE001
                pass
        self.app._log(f"[Setup] {self._mlabel()}: no code switched it. This monitor probably "
                      f"can't be switched by software (DDC/CI input-switch not supported) - "
                      f"you'd need its physical Input button.")
        messagebox.showinfo(
            "No working code",
            f"'{self._mlabel()}' didn't switch on any code. This monitor likely doesn't support "
            "input switching over DDC/CI (some don't), so software can't flip it - use the "
            "monitor's physical Input button for this one.",
            parent=self)
        self._advance_monitor()

    def _on_skip(self):
        if self._busy:
            return
        m = self._cur_monitor()
        if self._original is not None:
            try:
                ddc.set_input_source(m, self._original)
            except Exception:  # noqa: BLE001
                pass
        self._advance_monitor()

    def _advance_monitor(self):
        self._mi += 1
        self._start_monitor()

    def _finish(self):
        self.app._refresh_workspace_buttons()
        self.app.refresh_layout()
        self.grab_release()
        self.destroy()
        if self._found_any:
            messagebox.showinfo(
                "Setup complete",
                "Done! I've saved your Personal and Work workspaces. Use the big Personal / Work "
                "buttons on the main window to switch. Run this again any time to adjust.",
                parent=self.app)
        else:
            self.app._log("Set up switching: finished - no monitors could be switched by software.")

    def _stop(self):
        if self._busy:
            return
        # best-effort restore of the current monitor
        try:
            m = self._cur_monitor()
            if self._original is not None:
                ddc.set_input_source(m, self._original)
        except Exception:  # noqa: BLE001
            pass
        self.grab_release()
        self.destroy()
        self.app._refresh_workspace_buttons()


class SetupWindow(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Setup - Monitors & Workspaces")
        self.configure(bg=C("bg"))
        self.geometry("760x600")
        self.transient(app)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        self.tab_mon = ttk.Frame(nb)
        self.tab_ws = ttk.Frame(nb)
        nb.add(self.tab_mon, text="Monitors & Capture")
        nb.add(self.tab_ws, text="Workspaces")

        self._build_monitors_tab()
        self._build_workspaces_tab()

    # --- monitors tab: detect + capture current inputs as a workspace ---
    def _build_monitors_tab(self):
        f = self.tab_mon
        ttk.Label(f, text="Detected monitors (with their current input value):",
                  style="TLabel").pack(anchor="w", padx=10, pady=(10, 4))

        cols = ("idx", "name", "serial", "current")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=8)
        for c, w, t in [("idx", 50, "#"), ("name", 240, "Monitor"),
                        ("serial", 160, "Serial"), ("current", 200, "Current input")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x", padx=10)

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="Refresh / Read current inputs", command=self._refresh_tree).pack(side="left")
        ttk.Button(btns, text="Capture these as a new workspace…", command=self._capture_workspace).pack(side="left", padx=6)
        ttk.Button(btns, text="New workspace → choose target input…", command=self._new_manual_workspace).pack(side="left")

        tip = ("Two ways to make a workspace:\n"
               "  • Capture - reads the inputs the monitors are on RIGHT NOW (use this on\n"
               "    the machine you're sitting at, e.g. capture 'Personal' while on Personal).\n"
               "  • Choose target input - pick the input you want the monitors to switch TO\n"
               "    (use this to build the 'go to the other PC' profile you can't capture,\n"
               "    e.g. on the Work PC build 'Go to Personal' = all monitors → DisplayPort).")
        ttk.Label(f, text=tip, style="Muted.TLabel", justify="left").pack(anchor="w", padx=10, pady=6)

        self._refresh_tree()

    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        def work():
            try:
                mons = ddc.list_monitors()
            except ddc.DDCError as e:
                self.app._post( lambda: messagebox.showerror("DDC error", str(e), parent=self))
                return
            self.app.detected = mons
            rows = []
            for m in mons:
                cur = ddc.get_input_source(m)
                cur_txt = f"0x{cur:02X}  {label_for_value(cur)}" if cur is not None else "unreadable"
                rows.append((m, cur, cur_txt))
            def fill():
                for m, cur, cur_txt in rows:
                    self.tree.insert("", "end", iid=str(m.index),
                                     values=(m.index, m.name or f"Monitor {m.index}", m.serial, cur_txt))
                if not rows:
                    self.tree.insert("", "end", values=("", "No monitors detected", "", ""))
            self.app._post( fill)
        threading.Thread(target=work, daemon=True).start()

    def _capture_workspace(self):
        mons = self.app.detected
        if not mons:
            messagebox.showinfo("Nothing to capture", "Detect monitors first.", parent=self)
            return
        name = simpledialog.askstring("Workspace name", "Name this workspace (e.g. Personal, Work):", parent=self)
        if not name:
            return
        assignments = []
        unreadable = []
        for m in mons:
            cur = ddc.get_input_source(m)
            if cur is None:
                unreadable.append(m.display_label)
                continue
            assignments.append(profiles.Assignment(
                monitor_id=m.stable_id,
                monitor_label=m.name or f"Monitor {m.index}",
                value=cur,
                value_label=label_for_value(cur),
            ))
        if not assignments:
            messagebox.showwarning("No readable inputs",
                                   "Could not read the current input on any monitor.", parent=self)
            return
        self.app.store.upsert(profiles.Workspace(name=name, assignments=assignments))
        profiles.save(self.app.store)
        self.app._refresh_workspace_buttons()
        self._reload_ws_list()
        msg = f"Captured '{name}' with {len(assignments)} monitor(s)."
        if unreadable:
            msg += "\nUnreadable (skipped): " + ", ".join(unreadable)
        messagebox.showinfo("Captured", msg, parent=self)

    def _new_manual_workspace(self):
        """Build a workspace by choosing the target input all monitors should
        switch TO - no need to be on that input to capture it."""
        mons = self.app.detected
        if not mons:
            messagebox.showinfo("Detect first",
                                "Click 'Refresh / Read current inputs' first so the app knows "
                                "which monitors to include.", parent=self)
            return

        panel, txt, acc, dim = C("panel"), C("txt"), C("acc"), C("dim")
        dlg = tk.Toplevel(self)
        dlg.title("New workspace - choose target input")
        dlg.configure(bg=panel)
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="New workspace", bg=panel, fg=acc,
                 font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(dlg, text=f"All {len(mons)} detected monitor(s) will be set to the input you pick.",
                 bg=panel, fg=dim, font=("Segoe UI", 9)).pack(anchor="w", padx=16)

        nrow = tk.Frame(dlg, bg=panel)
        nrow.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(nrow, text="Name", bg=panel, fg=txt, font=("Segoe UI", 10), width=6, anchor="w").pack(side="left")
        name_var = tk.StringVar(value="Go to Personal")
        tk.Entry(nrow, textvariable=name_var, width=28, bg=C("panel2"), fg=txt,
                 insertbackground=txt, relief="flat", font=("Segoe UI", 10),
                 highlightthickness=1, highlightbackground=C("line"),
                 highlightcolor=C("acc2")).pack(side="left", ipady=3)

        irow = tk.Frame(dlg, bg=panel)
        irow.pack(fill="x", padx=16, pady=4)
        tk.Label(irow, text="Input", bg=panel, fg=txt, font=("Segoe UI", 10), width=6, anchor="w").pack(side="left")
        combo, get_value = _make_input_combo(irow, current_value=0x0F, width=30)
        combo.pack(side="left")

        tk.Label(dlg, text="Pick the input you want the monitors to switch TO (e.g. 'HDMI 2' to reach\n"
                           "the PC on your monitors' HDMI 2 port). If it doesn't switch, your monitor\n"
                           "may use a non-standard code - try another from the list.",
                 bg=panel, fg=dim, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=16, pady=(6, 0))

        def create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Name needed", "Give the workspace a name.", parent=dlg)
                return
            value = get_value()
            if value is None:
                messagebox.showwarning("Pick an input",
                                       "Choose an input from the list (not the separator line).",
                                       parent=dlg)
                return
            assignments = [
                profiles.Assignment(
                    monitor_id=m.stable_id,
                    monitor_label=m.name or f"Monitor {m.index}",
                    value=value,
                    value_label=friendly_label_for_value(value),
                )
                for m in mons
            ]
            self.app.store.upsert(profiles.Workspace(name=name, assignments=assignments))
            profiles.save(self.app.store)
            self.app._refresh_workspace_buttons()
            self._reload_ws_list()
            dlg.destroy()
            messagebox.showinfo(
                "Created",
                f"Workspace '{name}' created: all {len(assignments)} monitor(s) \u2192 "
                f"{friendly_label_for_value(value)}.\nIt's now a button on the main window.",
                parent=self)

        brow = tk.Frame(dlg, bg=panel)
        brow.pack(fill="x", padx=16, pady=14)
        tk.Button(brow, text="Create workspace", command=create, bg=acc, fg=C("acc_ink"),
                  activebackground=C("acc2"), activeforeground=C("acc_ink"), relief="flat",
                  font=("Segoe UI Semibold", 10), padx=16, pady=6, cursor="hand2", bd=0).pack(side="left")
        tk.Button(brow, text="Cancel", command=dlg.destroy, bg=panel, fg=dim,
                  activebackground=C("panel2"), activeforeground=txt, relief="flat",
                  font=("Segoe UI", 10), padx=12, pady=6, cursor="hand2", bd=0).pack(side="right")

    # --- workspaces tab: edit existing ---
    def _build_workspaces_tab(self):
        f = self.tab_ws
        left = ttk.Frame(f)
        left.pack(side="left", fill="y", padx=10, pady=10)
        ttk.Label(left, text="Workspaces").pack(anchor="w")
        self.ws_list = tk.Listbox(left, height=16, width=22, bg=C("panel"), fg=C("txt"),
                                  selectbackground=C("acc"), selectforeground=C("acc_ink"),
                                  relief="flat", font=("Segoe UI", 10), exportselection=False,
                                  highlightthickness=1, highlightbackground=C("line"))
        self.ws_list.pack(fill="y", expand=True, pady=4)
        self.ws_list.bind("<<ListboxSelect>>", lambda e: self._show_ws_detail())
        wsb = ttk.Frame(left)
        wsb.pack(fill="x")
        ttk.Button(wsb, text="Rename", command=self._rename_ws).pack(side="left")
        ttk.Button(wsb, text="Delete", command=self._delete_ws).pack(side="left", padx=4)

        self.detail = ttk.Frame(f)
        self.detail.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        self._reload_ws_list()

    def _reload_ws_list(self):
        self.ws_list.delete(0, "end")
        for w in self.app.store.workspaces:
            self.ws_list.insert("end", w.name)

    def _selected_ws(self):
        sel = self.ws_list.curselection()
        if not sel:
            return None
        return self.app.store.workspaces[sel[0]]

    def _show_ws_detail(self):
        ws = self._selected_ws()
        if not ws:
            # No selection (e.g. a spurious event) - leave the current pane intact.
            return
        for w in self.detail.winfo_children():
            w.destroy()
        ttk.Label(self.detail, text=f"Assignments for '{ws.name}'").pack(anchor="w")
        ttk.Label(self.detail, text="Choose each monitor's input - or 'Leave unchanged' to\n"
                                    "not touch that monitor when this workspace is applied:",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        self._editors = []
        for a in ws.assignments:
            rowf = ttk.Frame(self.detail)
            rowf.pack(fill="x", pady=3)
            ttk.Label(rowf, text=a.monitor_label, width=26).pack(side="left")
            combo, get_value = _make_input_combo(rowf, current_value=a.value, width=32, include_skip=True)
            combo.pack(side="left", padx=6)
            ttk.Button(rowf, text="Test", command=lambda a=a, gv=get_value: self._test_value(a, gv)).pack(side="left")
            ttk.Button(rowf, text="Scan", command=lambda a=a: self._scan_inputs(a)).pack(side="left", padx=(4, 0))
            self._editors.append((a, get_value))

        ttk.Label(self.detail,
                  text="Not switching? Click Scan to auto-detect which input codes this monitor\n"
                       "actually accepts (do it with the other PC powered on).",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Button(self.detail, text="Save changes", command=self._save_ws_edits).pack(anchor="w", pady=10)

    def _scan_inputs(self, a: profiles.Assignment):
        live = {m.stable_id: m for m in (self.app.detected or [])}
        m = live.get(a.monitor_id)
        if not m:
            messagebox.showwarning("Not attached",
                                   f"Monitor '{a.monitor_label}' isn't currently detected. "
                                   "Go to the Monitors tab and Refresh.", parent=self)
            return
        self.app.scan_monitor(m, a.monitor_label)

    def _test_value(self, a: profiles.Assignment, get_value):
        val = get_value()
        if val is None:
            messagebox.showwarning("Pick an input", "Choose an input first.", parent=self)
            return
        if val == SKIP_INPUT:
            messagebox.showinfo("Nothing to test",
                                "This monitor is set to 'Leave unchanged', so there's nothing to "
                                "switch - it will be skipped when the workspace is applied.",
                                parent=self)
            return
        live = {m.stable_id: m for m in (self.app.detected or [])}
        m = live.get(a.monitor_id)
        if not m:
            messagebox.showwarning("Not attached",
                                   f"Monitor '{a.monitor_label}' isn't currently detected. "
                                   "Go to the Monitors tab and Refresh.", parent=self)
            return
        name = friendly_label_for_value(val)
        self.app._log(f"[Test] {a.monitor_label} -> {name} (0x{val:02X}) - verifying…")

        def work():
            try:
                applied, readback = ddc.set_input_source_verified(m, val)
            except Exception as e:  # noqa: BLE001
                self.app._post(lambda e=e: messagebox.showerror("Test failed", str(e), parent=self))
                return
            if applied:
                self.app._post(lambda: self.app._log(f"[Test] {a.monitor_label}: switched to {name} \u2713 (confirmed)"))
            else:
                rb = f"0x{readback:02X} ({friendly_label_for_value(readback)})" if readback is not None else "unreadable"
                self.app._post(lambda rb=rb: self.app._log(
                    f"[Test] {a.monitor_label}: monitor IGNORED {name} - still on {rb}. "
                    f"Wrong code for this monitor, or that input has no signal (turn the other PC on)."))
        threading.Thread(target=work, daemon=True).start()

    def _save_ws_edits(self):
        ws = self._selected_ws()
        if not ws:
            return
        for a, get_value in self._editors:
            val = get_value()
            if val is None:
                continue
            a.value = val
            a.value_label = friendly_label_for_value(val)
        profiles.save(self.app.store)
        self.app._refresh_workspace_buttons()
        messagebox.showinfo("Saved", f"Workspace '{ws.name}' updated.", parent=self)

    def _rename_ws(self):
        ws = self._selected_ws()
        if not ws:
            return
        new = simpledialog.askstring("Rename", "New name:", initialvalue=ws.name, parent=self)
        if new:
            ws.name = new
            profiles.save(self.app.store)
            self._reload_ws_list()
            self.app._refresh_workspace_buttons()

    def _delete_ws(self):
        ws = self._selected_ws()
        if not ws:
            return
        if messagebox.askyesno("Delete", f"Delete workspace '{ws.name}'?", parent=self):
            self.app.store.remove(ws.name)
            profiles.save(self.app.store)
            self._reload_ws_list()
            self._show_ws_detail()
            self.app._refresh_workspace_buttons()


if __name__ == "__main__":
    App().mainloop()
