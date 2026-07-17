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


def _icon_image():
    img = Image.new("RGBA", (64, 64), (10, 14, 10, 255))
    d = ImageDraw.Draw(img)
    green = (0, 255, 0, 255)
    d.rectangle([8, 12, 56, 44], outline=green, width=4)     # screen
    d.rectangle([27, 44, 37, 50], fill=green)                # neck
    d.rectangle([18, 52, 46, 57], fill=green)                # base
    return img


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def start(self) -> bool:
        if not AVAILABLE:
            return False
        self.icon = pystray.Icon("monitor_kvm", _icon_image(), "Monitor Switcher")
        self.icon.menu = self._build_menu()
        threading.Thread(target=self.icon.run, daemon=True).start()
        return True

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
