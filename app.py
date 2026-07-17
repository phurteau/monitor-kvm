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
from vcp_inputs import COMMON_INPUTS, label_for_value

APP_TITLE = "Monitor Workspace Switcher"


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

        var = tk.StringVar()
        values = [f"{lbl}  (0x{v:02X})" for lbl, v in COMMON_INPUTS]
        combo = ttk.Combobox(top, textvariable=var, width=36, state="readonly", values=values)
        if cur is not None:
            var.set(f"{label_for_value(cur)}  (0x{cur:02X})")
        else:
            combo.current(0)
        combo.pack(padx=12, pady=10)

        tk.Label(top, text="Setting an input may switch this monitor to another\nmachine - use its physical buttons to return if needed.",
                 bg=panel, fg=dim, font=("Segoe UI", 8), justify="left").pack(anchor="w", padx=12)

        btns = tk.Frame(top, bg=panel)
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
                  bg=acc, fg=ink, activebackground=acc2, activeforeground=ink,
                  relief="flat", font=("Segoe UI Semibold", 10), padx=14, pady=6,
                  cursor="hand2", bd=0).pack(side="left")
        tk.Button(btns, text="Test (keep open)", command=lambda: do_set(False),
                  bg=panel2, fg=txt, activebackground=panel, activeforeground=txt,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", highlightthickness=1, highlightbackground=line, bd=0).pack(side="left", padx=6)
        tk.Button(btns, text="Close", command=top.destroy,
                  bg=panel, fg=dim, activebackground=panel2, activeforeground=txt,
                  relief="flat", font=("Segoe UI", 10), padx=10, pady=6,
                  cursor="hand2", bd=0).pack(side="right")


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
        self.ws_list = tk.Listbox(left, height=16, width=22, bg=C("panel"), fg=C("txt"),
                                  selectbackground=C("acc"), selectforeground=C("acc_ink"),
                                  relief="flat", font=("Segoe UI", 10),
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
