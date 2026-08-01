"""
Minimal view: a frameless, always-on-top, draggable pill of workspace buttons.

The full window is great for setup but heavy for the one thing done all day,
picking a workspace. Minimal view collapses the app to a floating bar that is
almost all buttons: a drag grip, one flat accent button per workspace, a
chevron to expand back to the full window, and a close button.

Design notes:
  * Frameless (overrideredirect) + topmost. On Windows the -topmost attribute
    must be set AFTER overrideredirect and re-asserted on show, or the bar sinks
    behind other windows; -toolwindow keeps it out of the taskbar/Alt-Tab where
    supported.
  * The bar owns no theme subscription of its own. The App is the single T
    subscriber and calls MiniBar.apply_theme(), so destroying the bar can never
    leak a callback.
  * Width is content-driven (natural pack, no fixed geometry width). Only the
    x/y position and a scale factor are persisted, through settings.py. On open
    the saved position is validated against the real per-display rectangles
    (layout.get_displays) so a monitor change can't strand the bar in the
    L-shaped dead space between staggered monitors; if it no longer fits any
    real display it resets to a sane primary-display default.
  * The pill has no native resize border, so a corner grip scales the whole bar
    (fonts and paddings together) between SCALE_MIN and SCALE_MAX, remembered.
"""

from __future__ import annotations

import tkinter as tk

import layout
import settings
from theme import THEME as T

# glyphs (kept as names so intent is obvious and easy to retune)
GRIP_GLYPH = "\u22ee"      # vertical ellipsis, the drag handle
EXPAND_GLYPH = "\u2921"    # north-east/south-west arrow, "back to full view"
CLOSE_GLYPH = "\u00d7"     # multiplication sign, "quit"
RESIZE_GLYPH = "\u25e2"    # lower-right triangle, the scale/resize corner

# The pill has no native resize border (it is overrideredirect), so the corner
# grip scales the whole bar between these bounds and the factor is remembered.
SCALE_MIN = 0.8
SCALE_MAX = 2.4


def C(key):
    """Current value of a theme token (re-read live on every use)."""
    return T.t(key)


def _pick_position(saved_x, saved_y, w, h, displays):
    """Choose where to place a w x h bar, given the real per-display rectangles.

    Pure geometry so it is unit-testable without a Tk display or real monitors.
    `displays` is any sequence of objects exposing .x/.y/.width/.height/.primary
    (layout.DisplayInfo). Returns an (x, y) tuple, or None when `displays` is
    empty so the caller can fall back to its own vroot/screen clamp.

    The saved position is honoured only when the bar would be substantially
    visible on SOME single real display (at least half its width and its full
    height inside that display), then nudge-clamped fully onto that same
    display. Anything else - no saved value, a position in the L-shaped dead
    space between staggered monitors, or a wildly out-of-range value - resets to
    the default: horizontally centered with y = 8 on the primary display, using
    that display's own origin (the primary is not always at 0,0).
    """
    if not displays:
        return None

    primary = next((d for d in displays if d.primary), displays[0])
    default = (primary.x + (primary.width - w) // 2, primary.y + 8)

    if not isinstance(saved_x, int) or not isinstance(saved_y, int):
        return default

    for d in displays:
        # Intersection of the bar rect with this display rect.
        iw = min(saved_x + w, d.x + d.width) - max(saved_x, d.x)
        ih = min(saved_y + h, d.y + d.height) - max(saved_y, d.y)
        if iw >= w * 0.5 and ih >= h:
            # Substantially on this display: pull it fully back onto THIS one.
            nx = max(d.x, min(saved_x, d.x + d.width - w))
            ny = max(d.y, min(saved_y, d.y + d.height - h))
            return (nx, ny)

    return default


class MiniBar(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        # Accessible title even though the frame is hidden (screen readers, and
        # it labels the entry in tools that still enumerate toolwindows).
        self.title("Monitor Switcher - Minimal")

        self.overrideredirect(True)
        # -topmost AFTER overrideredirect (Windows z-order ordering matters).
        self.attributes("-topmost", True)
        try:
            self.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        self.configure(bg=C("panel"))

        self._drag_off = (0, 0)
        self._btns: list[tk.Button] = []
        self._flash_jobs: dict[int, str] = {}
        # Remembered scale factor for the whole pill (see the corner grip).
        self._scale = self._load_scale()
        self._resize_start = (0, 1.0)

        # 1px accent border over a panel fill => a floating pill on any wallpaper
        self.border = tk.Frame(self, bg=C("panel"), highlightthickness=1,
                               highlightbackground=C("acc"), highlightcolor=C("acc"))
        self.border.pack(fill="both", expand=True)
        self.bar = tk.Frame(self.border, bg=C("panel"))
        self.bar.pack(fill="both", expand=True, padx=2, pady=2)

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Full view", command=self.app._exit_minimal)
        self._menu.add_command(label="Toggle Light / Dark", command=self.app._toggle_theme)
        self._menu.add_separator()
        self._menu.add_command(label="Exit", command=self.app._quit_app)
        self._style_menu()

        self.build()

        # Ctrl+M toggles back to the full window from within the bar too.
        self.bind("<Control-m>", lambda e: self.app._toggle_minimal())
        self.bind("<Control-M>", lambda e: self.app._toggle_minimal())

        self._restore_position()
        # Re-assert topmost once mapped (some WMs reset it on first map).
        self.after(80, lambda: self._safe_attr("-topmost", True))

    # ---------- construction ----------
    def build(self):
        """(Re)build the bar's row of widgets from the current workspaces."""
        for w in self.bar.winfo_children():
            w.destroy()
        self._btns = []

        self._grip = tk.Label(self.bar, text=GRIP_GLYPH, bg=C("panel"), fg=C("dim"),
                              font=("Segoe UI", 12), cursor="fleur", padx=4)
        self._grip.pack(side="left")
        self._bind_drag(self._grip)
        self._bind_drag(self.bar)
        self._bind_menu(self.bar)
        self._bind_menu(self._grip)

        if not self.app.store.workspaces:
            # Empty state: a single button that sends the user into setup.
            b = tk.Button(self.bar, text="Set up...", command=self._go_setup,
                          bg=C("acc"), fg=C("acc_ink"), activebackground=C("acc2"),
                          activeforeground=C("acc_ink"), relief="flat", bd=0,
                          font=("Segoe UI Semibold", 10), padx=12, pady=6, cursor="hand2")
            b.pack(side="left", padx=4)
            self._btns.append(b)
        else:
            for ws in self.app.store.workspaces:
                b = tk.Button(self.bar, text=ws.name,
                              bg=C("acc"), fg=C("acc_ink"), activebackground=C("acc2"),
                              activeforeground=C("acc_ink"), relief="flat", bd=0,
                              font=("Segoe UI Semibold", 10), padx=12, pady=6, cursor="hand2")
                # Pass the button in directly so the flash is unambiguous even if
                # two workspaces share a name.
                b.configure(command=lambda w=ws, btn=b: self._switch(w, btn))
                b.pack(side="left", padx=(4, 0))
                self._bind_menu(b)
                self._btns.append(b)

        self._chevron = tk.Button(self.bar, text=EXPAND_GLYPH, command=self.app._exit_minimal,
                                  bg=C("panel"), fg=C("dim"), activebackground=C("panel2"),
                                  activeforeground=C("txt"), relief="flat", bd=0,
                                  font=("Segoe UI", 11), padx=8, pady=6, cursor="hand2")
        self._chevron.pack(side="left", padx=(6, 0))
        self._close = tk.Button(self.bar, text=CLOSE_GLYPH, command=self.app._quit_app,
                                bg=C("panel"), fg=C("dim"), activebackground=C("panel2"),
                                activeforeground=C("txt"), relief="flat", bd=0,
                                font=("Segoe UI", 11), padx=8, pady=6, cursor="hand2")
        self._close.pack(side="left")

        # Corner grip: drag to scale the whole pill (frameless, so no native border).
        self._resize = tk.Label(self.bar, text=RESIZE_GLYPH, bg=C("panel"), fg=C("dim"),
                                font=("Segoe UI", 11), cursor="size_nw_se", padx=2)
        self._resize.pack(side="left", padx=(2, 0))
        self._bind_resize(self._resize)

        # Right-click opens the context menu anywhere on the bar, including the
        # chevron, close and resize glyphs.
        self._bind_menu(self._chevron)
        self._bind_menu(self._close)
        self._bind_menu(self._resize)

        self._apply_scale()

    # ---------- theming ----------
    def apply_theme(self):
        """Repaint every widget after a theme/accent change (driven by the App)."""
        if not self.winfo_exists():
            return
        self.configure(bg=C("panel"))
        self.border.configure(bg=C("panel"), highlightbackground=C("acc"), highlightcolor=C("acc"))
        self.bar.configure(bg=C("panel"))
        self._grip.configure(bg=C("panel"), fg=C("dim"))
        self._resize.configure(bg=C("panel"), fg=C("dim"))
        for b in self._btns:
            b.configure(bg=C("acc"), fg=C("acc_ink"), activebackground=C("acc2"),
                        activeforeground=C("acc_ink"))
        for b in (self._chevron, self._close):
            b.configure(bg=C("panel"), fg=C("dim"), activebackground=C("panel2"),
                        activeforeground=C("txt"))
        self._style_menu()

    def _style_menu(self):
        try:
            self._menu.configure(bg=C("panel"), fg=C("txt"), activebackground=C("acc"),
                                 activeforeground=C("acc_ink"), bd=0, relief="flat")
        except tk.TclError:
            pass

    # ---------- actions ----------
    def _switch(self, ws, btn=None):
        self.app.apply_workspace(ws)
        self._flash(btn)

    def _go_setup(self):
        self.app._exit_minimal()
        self.app.start_guided_setup()

    def _flash(self, btn):
        """Brief busy cue on a clicked button (the activity log isn't visible)."""
        if btn is None or not btn.winfo_exists():
            return
        btn.configure(bg=C("acc2"))
        old = self._flash_jobs.get(id(btn))
        if old:
            try:
                self.after_cancel(old)
            except tk.TclError:
                pass

        def restore():
            if btn.winfo_exists():
                btn.configure(bg=C("acc"))
            self._flash_jobs.pop(id(btn), None)

        self._flash_jobs[id(btn)] = self.after(600, restore)

    # ---------- dragging ----------
    def _bind_drag(self, widget):
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_end)

    def _bind_menu(self, widget):
        widget.bind("<Button-3>", self._popup_menu)

    def _drag_start(self, event):
        self._drag_off = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event):
        x = event.x_root - self._drag_off[0]
        y = event.y_root - self._drag_off[1]
        self.geometry(f"+{x}+{y}")

    def _drag_end(self, event):
        self._save_position()

    def _popup_menu(self, event):
        self._style_menu()
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    # ---------- scaling ----------
    def _load_scale(self):
        try:
            s = float(settings.get("mini_scale", 1.0))
        except (TypeError, ValueError):
            s = 1.0
        return max(SCALE_MIN, min(SCALE_MAX, s))

    def _apply_scale(self):
        """Resize every glyph and button font/padding to the current scale.

        The pill sets only its position (never a fixed geometry size), so growing
        the fonts and paddings lets the frameless window auto-size to content.
        """
        f = self._scale

        def sz(base):
            return max(6, round(base * f))

        self._grip.configure(font=("Segoe UI", sz(12)))
        self._resize.configure(font=("Segoe UI", sz(11)))
        for b in self._btns:
            b.configure(font=("Segoe UI Semibold", sz(10)), padx=sz(12), pady=sz(6))
        for b in (self._chevron, self._close):
            b.configure(font=("Segoe UI", sz(11)), padx=sz(8), pady=sz(6))

    def _bind_resize(self, widget):
        widget.bind("<Button-1>", self._resize_start_drag)
        widget.bind("<B1-Motion>", self._resize_move)
        widget.bind("<ButtonRelease-1>", self._resize_end)

    def _resize_start_drag(self, event):
        self._resize_start = (event.x_root, self._scale)

    def _resize_move(self, event):
        # Horizontal drag drives the scale: dragging the corner outward grows the
        # pill. ~300px of travel spans one full unit of scale.
        delta = event.x_root - self._resize_start[0]
        self._set_scale(self._resize_start[1] + delta / 300.0)

    def _resize_end(self, event):
        settings.update(mini_scale=self._scale)
        self._save_position()

    def _set_scale(self, scale):
        scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        if abs(scale - self._scale) < 0.01:
            return
        self._scale = scale
        self._apply_scale()

    # ---------- position memory ----------
    def _save_position(self):
        settings.update(mini_x=self.winfo_x(), mini_y=self.winfo_y())

    def _restore_position(self):
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()

        data = settings.load()
        sx = data.get("mini_x")
        sy = data.get("mini_y")

        # Real per-display rectangles are the source of truth so a stale position
        # can never land in the L-shaped dead space between staggered monitors.
        try:
            displays = layout.get_displays()
        except Exception:  # noqa: BLE001
            displays = []

        pos = _pick_position(sx, sy, w, h, displays)
        if pos is None:
            # get_displays() is unavailable (non-Win32, stubbed, or it failed);
            # keep the old vroot/screen clamp so nothing regresses.
            pos = self._fallback_position(sx, sy, w, h)

        self.geometry(f"+{pos[0]}+{pos[1]}")

    def _fallback_position(self, sx, sy, w, h):
        """Legacy virtual-desktop clamp, used only when real rects are absent."""
        vx = self.winfo_vrootx() or 0
        vy = self.winfo_vrooty() or 0
        vw = self.winfo_vrootwidth() or self.winfo_screenwidth()
        vh = self.winfo_vrootheight() or self.winfo_screenheight()

        if not isinstance(sx, int) or not isinstance(sy, int):
            sx = (self.winfo_screenwidth() - w) // 2
            sy = 8

        x = max(vx, min(sx, vx + vw - w))
        y = max(vy, min(sy, vy + vh - h))
        return (x, y)

    # ---------- lifecycle ----------
    def show(self):
        self.deiconify()
        self._safe_attr("-topmost", True)
        self.lift()

    def _safe_attr(self, name, value):
        try:
            if self.winfo_exists():
                self.attributes(name, value)
        except tk.TclError:
            pass

    def close(self):
        """Persist position, then tear the bar down."""
        try:
            self._save_position()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
