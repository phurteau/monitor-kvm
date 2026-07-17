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
import tray as tray_mod
import updater
from version import VERSION
from vcp_inputs import COMMON_INPUTS, label_for_value

APP_TITLE = "Monitor Workspace Switcher"
BG = "#000000"          # pure black background
CARD = "#0a0f0a"        # near-black raised panel
ACCENT = "#00ff00"      # pure green accent
ACCENT2 = "#00ff00"     # primary highlight (same green)
ACCENT_DIM = "#00b800"  # pressed / hover green
BTN_TXT = "#001400"     # dark text for on-green buttons
TXT = "#c8ffc8"         # soft green-white body text
MUTED = "#4f8f57"       # muted green-grey
BORDER = "#154a1e"      # subtle green border for non-primary boxes


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  v{VERSION}")
        self.configure(bg=BG)
        self.geometry("760x780")
        self.minsize(680, 640)

        self.store = profiles.load()
        self.detected: list[ddc.Monitor] = []
        self._layout_cache: list = []
        self._ui_queue: queue.Queue = queue.Queue()

        self._build_style()
        self._build_ui()
        self._refresh_workspace_buttons()
        self._log("Ready. Reading your display layout…")
        self.after(80, self._pump)
        self.after(200, self.refresh_layout)
        self.after(1500, lambda: self.check_updates(manual=False))

        # system tray (optional)
        self.tray = tray_mod.Tray(self)
        if self.tray.start():
            self._log("System tray active - right-click the tray icon to switch workspaces.")
            self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
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
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TXT, font=("Segoe UI", 10))
        style.configure("H1.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 16))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=CARD, foreground=TXT, font=("Segoe UI", 10))
        # dark buttons with green text/outline
        style.configure("TButton", font=("Segoe UI", 10), padding=6,
                        background=CARD, foreground=ACCENT, bordercolor=BORDER, focuscolor=ACCENT)
        style.map("TButton",
                  background=[("active", "#16261a")],
                  foreground=[("active", ACCENT)])
        style.configure("Big.TButton", font=("Segoe UI Semibold", 12), padding=12)
        # notebook + treeview dark theming for the setup window
        style.configure("TNotebook", background=BG, bordercolor=BORDER)
        style.configure("TNotebook.Tab", background=CARD, foreground=TXT, padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", "#16261a")],
                  foreground=[("selected", ACCENT)])
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TXT,
                        bordercolor=BORDER)
        style.configure("Treeview.Heading", background=BG, foreground=ACCENT)
        style.map("Treeview", background=[("selected", ACCENT_DIM)],
                  foreground=[("selected", BTN_TXT)])
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TXT)

    # ---------- main layout ----------
    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(16, 6))
        self.header_frame = header
        titlerow = ttk.Frame(header)
        titlerow.pack(fill="x")
        ttk.Label(titlerow, text="Monitor Workspace Switcher", style="H1.TLabel").pack(side="left")
        ttk.Label(titlerow, text=f"v{VERSION}", style="Muted.TLabel").pack(side="left", padx=(8, 0), anchor="s", pady=(0, 3))
        ttk.Label(header, text="One click flips your monitors between inputs (a software KVM).",
                  style="Muted.TLabel").pack(anchor="w")

        # update banner (hidden until an update is found)
        self.banner = tk.Frame(self, bg="#04140a", highlightbackground=ACCENT,
                               highlightthickness=1)
        self.banner_label = tk.Label(self.banner, text="", bg="#04140a", fg=ACCENT,
                                     font=("Segoe UI Semibold", 10), anchor="w", justify="left")
        self.banner_label.pack(side="left", padx=12, pady=8)
        self.banner_btn = tk.Button(self.banner, text="Download & Update", bg=ACCENT, fg=BTN_TXT,
                                    activebackground=ACCENT_DIM, activeforeground=BTN_TXT,
                                    relief="flat", font=("Segoe UI Semibold", 10), padx=14, pady=5,
                                    cursor="hand2", bd=0)
        self.banner_btn.pack(side="right", padx=(6, 12), pady=8)
        self.banner_dismiss = tk.Button(self.banner, text="Dismiss", bg="#04140a", fg=MUTED,
                                        activebackground="#0a2410", activeforeground=TXT,
                                        relief="flat", font=("Segoe UI", 9), padx=8, pady=5,
                                        cursor="hand2", bd=0, command=self._hide_banner)
        self.banner_dismiss.pack(side="right", pady=8)
        # not packed into the window until needed
        self._banner_info = None

        # live display layout map
        maphead = ttk.Frame(self)
        maphead.pack(fill="x", padx=18, pady=(12, 2))
        ttk.Label(maphead, text="DISPLAY LAYOUT", style="Muted.TLabel").pack(side="left")
        ttk.Button(maphead, text="Refresh", command=self.refresh_layout).pack(side="right")
        self.canvas = tk.Canvas(self, height=210, bg=CARD, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", padx=18)
        self.canvas.bind("<Configure>", lambda e: self._draw_layout())
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # workspace buttons area
        ttk.Label(self, text="WORKSPACES", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(10, 2))
        self.ws_frame = ttk.Frame(self)
        self.ws_frame.pack(fill="x", padx=18)

        # toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        ttk.Button(bar, text="Detect Monitors", command=self.detect_monitors).pack(side="left")
        ttk.Button(bar, text="Setup / Edit Workspaces", command=self.open_setup).pack(side="left", padx=6)
        ttk.Button(bar, text="Self-Test", command=self.self_test).pack(side="left")
        ttk.Button(bar, text="Check for Updates", command=lambda: self.check_updates(manual=True)).pack(side="right")

        # log
        ttk.Label(self, text="ACTIVITY", style="Muted.TLabel").pack(anchor="w", padx=18, pady=(6, 2))
        logwrap = ttk.Frame(self)
        logwrap.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.log = tk.Text(logwrap, height=10, bg=CARD, fg=TXT, insertbackground=TXT,
                           relief="flat", font=("Cascadia Mono", 9), wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logwrap, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set, state="disabled")

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
                bg=ACCENT, fg=BTN_TXT, activebackground=ACCENT_DIM, activeforeground=BTN_TXT,
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

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))

    def _hide_to_tray(self):
        self.withdraw()

    def _quit_app(self):
        t = getattr(self, "tray", None)
        if t is not None:
            t.stop()
        self.destroy()

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
        notes = f"  -  {info.notes.splitlines()[0]}" if info.notes else ""
        self.banner_label.config(text=f"Update available:  v{info.current}  \u2192  v{info.latest}{notes}")
        self.banner_btn.config(text="Download & Update", state="normal",
                               command=lambda: self._do_update(info))
        # place the banner just under the header, above the layout map
        self.banner.pack(fill="x", padx=18, pady=(4, 6), after=self.header_frame)

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
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
        py = sys.executable
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        launcher = pyw if os.path.exists(pyw) else py
        try:
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
            ok, miss = 0, 0
            for a in ws.assignments:
                m = live.get(a.monitor_id)
                if not m:
                    # try to match by index fallback
                    miss += 1
                    self._post( lambda a=a: self._log(f"  ! monitor '{a.monitor_label}' ({a.monitor_id}) not currently attached - skipped"))
                    continue
                try:
                    ddc.set_input_source(m, a.value)
                    ok += 1
                    self._post( lambda a=a: self._log(f"  \u2713 {a.monitor_label} -> {a.value_label or label_for_value(a.value)} (0x{a.value:02X})"))
                except Exception as e:
                    miss += 1
                    self._post( lambda e=e, a=a: self._log(f"  ! {a.monitor_label}: {e}"))
            self._post( lambda: self._log(f"Done: {ok} switched, {miss} skipped."))
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
                          fill=MUTED, font=("Segoe UI", 10))
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
            fill = "#0f1f10" if controllable else "#161616"
            border = ACCENT if d.primary else (BORDER if controllable else "#3a3a3a")
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
            in_color = ACCENT if (m and it["input"] is not None) else MUTED
            colors = [TXT, MUTED, MUTED, in_color, MUTED]
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
        top = tk.Toplevel(self)
        top.title("Set input")
        top.configure(bg=CARD)
        top.transient(self)
        top.geometry(f"+{sx}+{sy}")
        top.attributes("-topmost", True)

        d = it["display"]
        tk.Label(top, text=d.friendly or m.display_label, bg=CARD, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=12, pady=(10, 2))
        cur = it["input"]
        cur_txt = label_for_value(cur) if cur is not None else "unknown"
        tk.Label(top, text=f"Current input: {cur_txt}", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        var = tk.StringVar()
        values = [f"{lbl}  (0x{v:02X})" for lbl, v in COMMON_INPUTS]
        combo = ttk.Combobox(top, textvariable=var, width=36, state="readonly", values=values)
        if cur is not None:
            var.set(f"{label_for_value(cur)}  (0x{cur:02X})")
        else:
            combo.current(0)
        combo.pack(padx=12, pady=10)

        tk.Label(top, text="Setting an input may switch this monitor to another\nmachine - use its physical buttons to return if needed.",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=12)

        btns = tk.Frame(top, bg=CARD)
        btns.pack(fill="x", padx=12, pady=10)

        def parse(text):
            if "0x" in text:
                try:
                    return int(text.split("0x")[1].strip().rstrip(")"), 16)
                except ValueError:
                    return None
            return None

        def do_set(close=True):
            val = parse(var.get())
            if val is None:
                return
            def work():
                try:
                    ddc.set_input_source(m, val)
                    self._post(lambda: self._log(f"Set {d.friendly or m.stable_id} -> 0x{val:02X} ({label_for_value(val)})"))
                    self._post(self.refresh_layout)
                except Exception as e:  # noqa: BLE001
                    self._post(lambda e=e: self._log(f"Set failed: {e}"))
            threading.Thread(target=work, daemon=True).start()
            if close:
                top.destroy()

        tk.Button(btns, text="Set input", command=lambda: do_set(True),
                  bg=ACCENT, fg=BTN_TXT, activebackground=ACCENT_DIM, activeforeground=BTN_TXT,
                  relief="flat", font=("Segoe UI Semibold", 10), padx=14, pady=6,
                  cursor="hand2", bd=0).pack(side="left")
        tk.Button(btns, text="Test (keep open)", command=lambda: do_set(False),
                  bg=CARD, fg=ACCENT, activebackground="#16261a", activeforeground=ACCENT,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", bd=1).pack(side="left", padx=6)
        tk.Button(btns, text="Close", command=top.destroy,
                  bg=CARD, fg=MUTED, activebackground="#16261a", activeforeground=TXT,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", bd=0).pack(side="right")


class SetupWindow(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Setup - Monitors & Workspaces")
        self.configure(bg=BG)
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

        tip = ("Tip: The reliable way to build a workspace is to sit at the machine you want\n"
               "to capture (so its input is the one currently shown), read the current inputs,\n"
               "then click 'Capture'. Do this on each PC, giving each capture a name\n"
               "(e.g. 'Personal', 'Work'). The buttons on the main window then flip between them.")
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

    # --- workspaces tab: edit existing ---
    def _build_workspaces_tab(self):
        f = self.tab_ws
        left = ttk.Frame(f)
        left.pack(side="left", fill="y", padx=10, pady=10)
        ttk.Label(left, text="Workspaces").pack(anchor="w")
        self.ws_list = tk.Listbox(left, height=16, width=22, bg=CARD, fg=TXT,
                                  selectbackground=ACCENT, relief="flat", font=("Segoe UI", 10))
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
        for w in self.detail.winfo_children():
            w.destroy()
        ws = self._selected_ws()
        if not ws:
            return
        ttk.Label(self.detail, text=f"Assignments for '{ws.name}'").pack(anchor="w")
        ttk.Label(self.detail, text="Each monitor and the input it will switch to:",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        self._editors = []
        for a in ws.assignments:
            rowf = ttk.Frame(self.detail)
            rowf.pack(fill="x", pady=3)
            ttk.Label(rowf, text=a.monitor_label, width=26).pack(side="left")
            var = tk.StringVar()
            combo = ttk.Combobox(rowf, textvariable=var, width=34, state="readonly",
                                 values=[f"{lbl}  (0x{v:02X})" for lbl, v in COMMON_INPUTS])
            # preselect current
            cur_disp = f"{a.value_label or label_for_value(a.value)}  (0x{a.value:02X})"
            var.set(cur_disp)
            combo.pack(side="left", padx=6)
            ttk.Button(rowf, text="Test", command=lambda a=a, var=var: self._test_value(a, var)).pack(side="left")
            self._editors.append((a, var))

        ttk.Button(self.detail, text="Save changes", command=self._save_ws_edits).pack(anchor="w", pady=10)

    def _parse_combo(self, text: str) -> int:
        # extract 0xXX
        if "0x" in text:
            try:
                return int(text.split("0x")[1].strip().rstrip(")"), 16)
            except ValueError:
                pass
        return 0

    def _test_value(self, a: profiles.Assignment, var: tk.StringVar):
        val = self._parse_combo(var.get())
        live = {m.stable_id: m for m in (self.app.detected or [])}
        m = live.get(a.monitor_id)
        if not m:
            messagebox.showwarning("Not attached",
                                   f"Monitor '{a.monitor_label}' isn't currently detected. "
                                   "Go to the Monitors tab and Refresh.", parent=self)
            return
        try:
            ddc.set_input_source(m, val)
            self.app._log(f"[Test] {a.monitor_label} -> 0x{val:02X}")
        except Exception as e:
            messagebox.showerror("Test failed", str(e), parent=self)

    def _save_ws_edits(self):
        ws = self._selected_ws()
        if not ws:
            return
        for a, var in self._editors:
            val = self._parse_combo(var.get())
            a.value = val
            a.value_label = label_for_value(val)
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
