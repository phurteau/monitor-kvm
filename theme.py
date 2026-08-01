"""
Token-based dual-theme engine. A tkinter port of the CSS custom-property
design system.

Web original used CSS variables on :root (overridden per data-theme) plus a
user-chosen ACCENT persisted in localStorage. Here:

  * Token dicts per theme live in _BASE (the neutral surfaces).
  * A single accent hex derives --acc2 / --acc-ink at runtime (derive_accent).
  * The active theme + accent persist to settings.json (our "localStorage").
  * Widgets can't cascade in tkinter, so the App calls THEME.subscribe(cb) and
    re-applies colors on any change; ttk styles are reconfigured centrally.

Token meanings (mirror the CSS):
  bg/bg2      app background layers (bg2 slightly lighter for insets)
  panel/panel2 card surfaces (panel2 = nested/hover surface)
  line        borders/dividers
  txt/dim     primary / muted text
  glow        shadow color
  acc         primary accent (user-changeable)
  acc2        brighter accent companion (hover/glow/focus/spinner)
  acc_ink     text/icon color that sits ON an accent fill (auto black/white)
  head1/head2 header gradient stops
  bodyglow    accent radial-glow tint used behind the header
"""

from __future__ import annotations

import colorsys

import settings

# Re-exported so older imports of theme.SETTINGS_PATH keep working; the file is
# now owned and merged by settings.py so theme+accent no longer clobber other
# keys (mini-bar position, last-used mode).
SETTINGS_PATH = settings.SETTINGS_PATH

DEFAULT_THEME = "dark"
DEFAULT_ACCENT = "#025500"
RADIUS = 12  # --radius:12px

# Neutral surface tokens per theme (everything except the accent-derived ones).
_BASE = {
    "dark": {
        "bg": "#000000", "bg2": "#060606",
        "panel": "#101012", "panel2": "#17171a",
        "line": "#2a2a2e",
        "txt": "#ededed", "dim": "#9a9a9a",
        "glow": "#000000",
        "head1": "#101012", "head2": "#000000",   # linear-gradient(90deg,panel,bg)
    },
    "light": {
        "bg": "#eef4ef", "bg2": "#e6ede8",
        "panel": "#ffffff", "panel2": "#f2f7f3",
        "line": "#cfe0d4",
        "txt": "#12251a", "dim": "#5c7a66",
        "glow": "#143c23",
        "head1": "#ffffff", "head2": "#eef4ef",
    },
}


# ---------- color helpers ----------
def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"bad hex: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{int(round(r)):02x}{int(round(g)):02x}{int(round(b)):02x}"


def is_valid_hex(h: str) -> bool:
    try:
        hex_to_rgb(h)
        return True
    except ValueError:
        return False


def yiq(hexstr: str) -> float:
    r, g, b = hex_to_rgb(hexstr)
    return (r * 299 + g * 587 + b * 114) / 1000.0


def _rel_lum(hexstr: str) -> float:
    """WCAG relative luminance."""
    def chan(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(hexstr)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(hex1: str, hex2: str) -> float:
    """WCAG contrast ratio between two colors (>=1)."""
    l1, l2 = _rel_lum(hex1), _rel_lum(hex2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def best_on(bg_hex: str, candidates: list[str]) -> str:
    """Return the candidate color with the highest contrast against bg."""
    return max(candidates, key=lambda c: contrast(c, bg_hex))


def derive_accent(accent_hex: str) -> dict:
    """From one accent hex, derive acc / acc2 / acc_ink (mirrors the JS)."""
    accent_hex = accent_hex if is_valid_hex(accent_hex) else DEFAULT_ACCENT
    r, g, b = hex_to_rgb(accent_hex)
    # acc2: same hue, saturation raised to >=0.45, lightness +0.20 capped ~0.75
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    s2 = max(s, 0.45)
    l2 = min(l + 0.20, 0.75)
    r2, g2, b2 = colorsys.hls_to_rgb(h, l2, s2)
    acc2 = rgb_to_hex(r2 * 255, g2 * 255, b2 * 255)
    # acc_ink: readable text on the accent fill
    ink = "#08140a" if yiq(accent_hex) > 140 else "#ffffff"
    return {"acc": accent_hex.lower(), "acc2": acc2, "acc_ink": ink}


class Theme:
    def __init__(self):
        self.name = DEFAULT_THEME
        self.accent = DEFAULT_ACCENT
        self._subs = []
        self.tok = {}
        self._load()
        self._recompute()

    # ----- persistence (settings.json, merged so other keys survive) -----
    def _load(self):
        data = settings.load()
        name = data.get("theme")
        accent = data.get("accent")
        if name in _BASE:
            self.name = name
        if accent and is_valid_hex(accent):
            self.accent = accent

    def _save(self):
        settings.update(theme=self.name, accent=self.accent)

    # ----- token computation -----
    def _recompute(self):
        base = dict(_BASE.get(self.name, _BASE[DEFAULT_THEME]))
        base.update(derive_accent(self.accent))
        self.tok = base

    # ----- public API -----
    def subscribe(self, cb):
        """Register a callback fired whenever theme/accent changes."""
        self._subs.append(cb)

    def _notify(self):
        for cb in list(self._subs):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def set_theme(self, name: str):
        if name in _BASE and name != self.name:
            self.name = name
            self._recompute()
            self._save()
            self._notify()

    def toggle_theme(self):
        self.set_theme("light" if self.name == "dark" else "dark")

    def set_accent(self, accent_hex: str):
        if is_valid_hex(accent_hex):
            self.accent = accent_hex.lower()
            self._recompute()
            self._save()
            self._notify()

    def reset_accent(self):
        self.set_accent(DEFAULT_ACCENT)

    # convenient token access: THEME["panel"] or THEME.t("panel")
    def __getitem__(self, key):
        return self.tok[key]

    def t(self, key):
        return self.tok.get(key, "#ff00ff")


# module-level singleton (the app imports and shares this)
THEME = Theme()
