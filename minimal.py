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
  * Width is content-driven (natural pack, no fixed geometry width); only the
    x/y position is persisted, through settings.py, and clamped back into the
    visible virtual desktop on open so a monitor change can't strand the bar
    off-screen.
"""

from __future__ import annotations

import tkinter as tk

import settings
from theme import THEME as T

# glyphs (kept as names so intent is obvious and easy to retune)
GRIP_GLYPH = "\u22ee"      # vertical ellipsis, the drag handle
EXPAND_GLYPH = "\u2921"    # north-east/south-west arrow, "back to full view"
CLOSE_GLYPH = "\u00d7"     # multiplication sign, "quit"


def C(key):
    """Current value of a theme token (re-read live on every use)."""
    return T.t(key)


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
                              command=lambda w=ws: self._switch(w),
                              bg=C("acc"), fg=C("acc_ink"), activebackground=C("acc2"),
                              activeforeground=C("acc_ink"), relief="flat", bd=0,
                              font=("Segoe UI Semibold", 10), padx=12, pady=6, cursor="hand2")
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

    # ---------- theming ----------
    def apply_theme(self):
        """Repaint every widget after a theme/accent change (driven by the App)."""
        if not self.winfo_exists():
            return
        self.configure(bg=C("panel"))
        self.border.configure(bg=C("panel"), highlightbackground=C("acc"), highlightcolor=C("acc"))
        self.bar.configure(bg=C("panel"))
        self._grip.configure(bg=C("panel"), fg=C("dim"))
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
    def _switch(self, ws):
        self.app.apply_workspace(ws)
        self._flash(next((b for b in self._btns if b["text"] == ws.name), None))

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

    # ---------- position memory ----------
    def _save_position(self):
        settings.update(mini_x=self.winfo_x(), mini_y=self.winfo_y())

    def _restore_position(self):
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()

        # Visible virtual desktop bounds (spans all monitors); fall back to the
        # primary screen if the virtual-root metrics are unavailable.
        vx = self.winfo_vrootx() or 0
        vy = self.winfo_vrooty() or 0
        vw = self.winfo_vrootwidth() or self.winfo_screenwidth()
        vh = self.winfo_vrootheight() or self.winfo_screenheight()

        data = settings.load()
        x = data.get("mini_x")
        y = data.get("mini_y")
        if not isinstance(x, int) or not isinstance(y, int):
            # Default: top-center of the primary screen.
            x = (self.winfo_screenwidth() - w) // 2
            y = 8

        # Clamp fully inside the virtual desktop so the bar is never stranded.
        x = max(vx, min(x, vx + vw - w))
        y = max(vy, min(y, vy + vh - h))
        self.geometry(f"+{x}+{y}")

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
