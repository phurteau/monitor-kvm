"""
HSV color-wheel accent picker (tkinter + PIL). A port of the web accent picker.

  * Circular HSV wheel: hue = angle around the circle, saturation = distance
    from center. A draggable dot marks the current hue/sat.
  * "Brightness" slider (HSV Value 0-100) repaints the wheel.
  * Hex text input (typing #rrggbb moves the dot) + live preview swatch.
  * "Reset to default" button.
  * Dragging the wheel or moving the slider updates the accent live via on_change.
"""

from __future__ import annotations

import colorsys
import math
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import theme as theme_mod

WHEEL = 220          # wheel diameter in px
_MARGIN = 6


def _render_wheel(diameter: int, value: float) -> Image.Image:
    """Render an HSV wheel at the given Value (brightness). Cached by caller."""
    r = diameter / 2.0
    img = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    px = img.load()
    for y in range(diameter):
        dy = y - r
        for x in range(diameter):
            dx = x - r
            dist = math.hypot(dx, dy)
            if dist <= r:
                hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
                sat = min(dist / r, 1.0)
                cr, cg, cb = colorsys.hsv_to_rgb(hue, sat, value)
                # soft anti-aliased edge
                a = 255 if dist <= r - 1 else int(255 * max(0.0, (r - dist)))
                px[x, y] = (int(cr * 255), int(cg * 255), int(cb * 255), a)
    return img


class AccentPicker(tk.Toplevel):
    def __init__(self, master, theme: theme_mod.Theme, on_change=None):
        super().__init__(master)
        self.theme = theme
        self.on_change = on_change
        self.title("Choose accent color")
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=theme["panel"])

        self._value = 1.0  # HSV Value (brightness)
        self._hue = 0.0
        self._sat = 0.0
        self._wheel_img = None
        self._photo = None

        pad = 14
        wrap = tk.Frame(self, bg=theme["panel"])
        wrap.pack(padx=pad, pady=pad)

        # wheel canvas
        self.canvas = tk.Canvas(wrap, width=WHEEL, height=WHEEL, bg=theme["panel"],
                                highlightthickness=0, bd=0, cursor="crosshair")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_wheel_drag)
        self.canvas.bind("<B1-Motion>", self._on_wheel_drag)

        # brightness slider
        srow = tk.Frame(wrap, bg=theme["panel"])
        srow.pack(fill="x", pady=(12, 4))
        tk.Label(srow, text="Brightness", bg=theme["panel"], fg=theme["dim"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.bright = tk.Scale(srow, from_=0, to=100, orient="horizontal",
                               showvalue=False, command=self._on_bright,
                               bg=theme["panel"], fg=theme["txt"], troughcolor=theme["panel2"],
                               highlightthickness=0, bd=0, sliderrelief="flat",
                               activebackground=theme["acc2"], length=150)
        self.bright.set(100)
        self.bright.pack(side="right")

        # hex row + preview
        hrow = tk.Frame(wrap, bg=theme["panel"])
        hrow.pack(fill="x", pady=(8, 4))
        tk.Label(hrow, text="Hex", bg=theme["panel"], fg=theme["dim"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.hex_var = tk.StringVar(value=theme.accent)
        self.hex_entry = tk.Entry(hrow, textvariable=self.hex_var, width=10,
                                  bg=theme["panel2"], fg=theme["txt"], insertbackground=theme["txt"],
                                  relief="flat", font=("Cascadia Mono", 10),
                                  highlightthickness=1, highlightbackground=theme["line"],
                                  highlightcolor=theme["acc2"])
        self.hex_entry.pack(side="left", padx=6, ipady=3)
        self.hex_entry.bind("<Return>", lambda e: self._apply_hex())
        self.hex_entry.bind("<FocusOut>", lambda e: self._apply_hex())
        self.preview = tk.Frame(hrow, width=34, height=26, bg=theme.accent,
                                highlightthickness=1, highlightbackground=theme["line"])
        self.preview.pack(side="right")
        self.preview.pack_propagate(False)

        # buttons
        brow = tk.Frame(wrap, bg=theme["panel"])
        brow.pack(fill="x", pady=(10, 0))
        tk.Button(brow, text="Reset to default", command=self._reset,
                  bg=theme["panel2"], fg=theme["txt"], activebackground=theme["panel"],
                  activeforeground=theme["txt"], relief="flat",
                  font=("Segoe UI", 9), padx=10, pady=5, cursor="hand2",
                  highlightthickness=1, highlightbackground=theme["line"]).pack(side="left")
        tk.Button(brow, text="Done", command=self.destroy,
                  bg=theme["acc"], fg=theme["acc_ink"], activebackground=theme["acc2"],
                  activeforeground=theme["acc_ink"], relief="flat",
                  font=("Segoe UI Semibold", 10), padx=16, pady=5, cursor="hand2",
                  bd=0).pack(side="right")

        # initialize from current accent
        self._set_from_hex(theme.accent, live=False)
        self._repaint_wheel()

    # ---------- wheel rendering ----------
    def _repaint_wheel(self):
        self._wheel_img = _render_wheel(WHEEL, self._value)
        self._photo = ImageTk.PhotoImage(self._wheel_img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._draw_dot()

    def _draw_dot(self):
        r = WHEEL / 2.0
        dx = math.cos(self._hue * 2 * math.pi) * self._sat * r
        dy = math.sin(self._hue * 2 * math.pi) * self._sat * r
        x = r + dx
        y = r + dy
        rr = 7
        # ring that contrasts on any hue
        self.canvas.create_oval(x - rr, y - rr, x + rr, y + rr,
                                outline="#ffffff", width=2)
        self.canvas.create_oval(x - rr - 1, y - rr - 1, x + rr + 1, y + rr + 1,
                                outline="#000000", width=1)

    # ---------- interaction ----------
    def _on_wheel_drag(self, event):
        r = WHEEL / 2.0
        dx = event.x - r
        dy = event.y - r
        dist = math.hypot(dx, dy)
        self._hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        self._sat = min(dist / r, 1.0)
        self._emit_from_hsv()
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._draw_dot()

    def _on_bright(self, _val):
        self._value = self.bright.get() / 100.0
        self._repaint_wheel()
        self._emit_from_hsv()

    def _emit_from_hsv(self):
        cr, cg, cb = colorsys.hsv_to_rgb(self._hue, self._sat, self._value)
        hexv = theme_mod.rgb_to_hex(cr * 255, cg * 255, cb * 255)
        self.hex_var.set(hexv)
        self._update_preview(hexv)
        if self.on_change:
            self.on_change(hexv)

    def _apply_hex(self):
        h = self.hex_var.get().strip()
        if not h.startswith("#"):
            h = "#" + h
        if theme_mod.is_valid_hex(h):
            self._set_from_hex(h, live=True)

    def _set_from_hex(self, hexv: str, live: bool):
        r, g, b = theme_mod.hex_to_rgb(hexv)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        self._hue, self._sat, self._value = h, s, v
        self.bright.set(int(round(v * 100)))
        self.hex_var.set(hexv.lower())
        self._update_preview(hexv)
        self._repaint_wheel()
        if live and self.on_change:
            self.on_change(hexv.lower())

    def _reset(self):
        self._set_from_hex(theme_mod.DEFAULT_ACCENT, live=True)

    def _update_preview(self, hexv: str):
        try:
            self.preview.configure(bg=hexv)
        except tk.TclError:
            pass
