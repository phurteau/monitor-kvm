"""
Optional system-tray switcher. Lets you flip workspaces without opening the
window. Degrades gracefully: if pystray/Pillow aren't installed, AVAILABLE is
False and the app just runs without a tray icon.
"""

from __future__ import annotations

import threading

try:
    import pystray
    from pystray import Menu, MenuItem
    from PIL import Image, ImageDraw
    AVAILABLE = True
except Exception:  # noqa: BLE001
    AVAILABLE = False


def _icon_image(accent=(0, 255, 0)):
    # Prefer the real app icon; fall back to a simple drawn glyph.
    try:
        import os
        from apppaths import resource_dir
        png = os.path.join(resource_dir(), "assets", "icon_256.png")
        if os.path.exists(png):
            return Image.open(png).convert("RGBA")
    except Exception:  # noqa: BLE001
        pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (*accent, 255)
    d.rectangle([8, 12, 56, 44], outline=col, width=4)     # screen
    d.rectangle([27, 44, 37, 50], fill=col)                # neck
    d.rectangle([18, 52, 46, 57], fill=col)                # base
    return img


def _accent_rgb(app):
    try:
        import theme as _t
        return _t.hex_to_rgb(_t.THEME["acc2"])
    except Exception:  # noqa: BLE001
        return (0, 255, 0)


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def start(self) -> bool:
        if not AVAILABLE:
            return False
        self.icon = pystray.Icon("monitor_kvm", _icon_image(_accent_rgb(self.app)),
                                 "Monitor Switcher")
        self.icon.menu = self._build_menu()
        threading.Thread(target=self.icon.run, daemon=True).start()
        return True

    def refresh_icon(self):
        if self.icon is not None:
            try:
                self.icon.icon = _icon_image(_accent_rgb(self.app))
            except Exception:  # noqa: BLE001
                pass

    def _build_menu(self):
        items = []
        for ws in self.app.store.workspaces:
            items.append(MenuItem(f"Switch to {ws.name}", self._make_apply(ws.name)))
        if items:
            items.append(Menu.SEPARATOR)
        items.append(MenuItem("Open Switcher", self._open, default=True))
        items.append(MenuItem("Quit", self._quit))
        return Menu(*items)

    def update_menu(self):
        if self.icon is not None:
            try:
                self.icon.menu = self._build_menu()
                self.icon.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def _make_apply(self, name: str):
        def handler(icon, item):
            self.app.apply_workspace_by_name(name)
        return handler

    def _open(self, icon, item):
        self.app._post(self.app._show_window)

    def _quit(self, icon, item):
        try:
            icon.stop()
        finally:
            self.app._post(self.app._quit_app)

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
