r"""
Read the live Windows display arrangement (position, size, orientation,
primary) via the Win32 API, so the GUI can draw the same picture you see in
Settings > System > Display > "Rearrange your displays".

Each display is keyed by its adapter device name (e.g. \\.\DISPLAY3), which is
exactly the prefix of ControlMyMonitor's "Monitor Device Name"
(\\.\DISPLAY3\Monitor0) -- so we can line up each layout box with its DDC
monitor and current input.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

CCHDEVICENAME = 32
CCHFORMNAME = 32

ENUM_CURRENT_SETTINGS = -1
DISPLAY_DEVICE_ACTIVE = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

# dmDisplayOrientation values
_ORIENT = {0: "Landscape", 1: "Portrait (90\u00b0)", 2: "Landscape (flipped)", 3: "Portrait (270\u00b0)"}


class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * CCHDEVICENAME),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_ulong),
        # display-device branch of the union
        ("dmPosition", POINTL),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * CCHFORMNAME),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_ulong),
        ("dmPelsWidth", ctypes.c_ulong),
        ("dmPelsHeight", ctypes.c_ulong),
        ("dmDisplayFlags", ctypes.c_ulong),
        ("dmDisplayFrequency", ctypes.c_ulong),
        ("dmICMMethod", ctypes.c_ulong),
        ("dmICMIntent", ctypes.c_ulong),
        ("dmMediaType", ctypes.c_ulong),
        ("dmDitherType", ctypes.c_ulong),
        ("dmReserved1", ctypes.c_ulong),
        ("dmReserved2", ctypes.c_ulong),
        ("dmPanningWidth", ctypes.c_ulong),
        ("dmPanningHeight", ctypes.c_ulong),
    ]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_ulong),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


@dataclass
class DisplayInfo:
    device_name: str      # e.g. \\.\DISPLAY3
    adapter: str          # adapter DeviceString
    friendly: str         # monitor friendly name (e.g. "LG HDR 4K")
    monitor_id: str       # MONITOR\... (matches ControlMyMonitor "Monitor ID")
    x: int
    y: int
    width: int            # effective (post-rotation) pixels
    height: int
    orientation: int
    primary: bool

    @property
    def orientation_label(self) -> str:
        return _ORIENT.get(self.orientation, f"Orientation {self.orientation}")

    @property
    def is_portrait(self) -> bool:
        return self.orientation in (1, 3) or self.height > self.width


def _try_set_dpi_aware() -> None:
    """Best-effort: report true pixel coordinates on high-DPI setups."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_displays(set_dpi_aware: bool = False) -> list[DisplayInfo]:
    if set_dpi_aware:
        _try_set_dpi_aware()

    user32 = ctypes.windll.user32
    displays: list[DisplayInfo] = []

    i = 0
    while True:
        adapter = DISPLAY_DEVICE()
        adapter.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(adapter), 0):
            break
        i += 1

        if not (adapter.StateFlags & DISPLAY_DEVICE_ACTIVE):
            continue

        # Monitor (child) info for a friendly name + stable MONITOR\ id.
        mon = DISPLAY_DEVICE()
        mon.cb = ctypes.sizeof(DISPLAY_DEVICE)
        friendly = ""
        monitor_id = ""
        if user32.EnumDisplayDevicesW(adapter.DeviceName, 0, ctypes.byref(mon), 0):
            friendly = mon.DeviceString
            monitor_id = mon.DeviceID

        dm = DEVMODE()
        dm.dmSize = ctypes.sizeof(DEVMODE)
        if not user32.EnumDisplaySettingsW(adapter.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            continue

        displays.append(
            DisplayInfo(
                device_name=adapter.DeviceName,
                adapter=adapter.DeviceString,
                friendly=friendly or adapter.DeviceString,
                monitor_id=monitor_id,
                x=dm.dmPosition.x,
                y=dm.dmPosition.y,
                width=int(dm.dmPelsWidth),
                height=int(dm.dmPelsHeight),
                orientation=int(dm.dmDisplayOrientation),
                primary=bool(adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE) or (dm.dmPosition.x == 0 and dm.dmPosition.y == 0),
            )
        )

    return displays


if __name__ == "__main__":
    for d in get_displays():
        star = " *PRIMARY" if d.primary else ""
        print(f"{d.device_name}  {d.friendly!r}  {d.width}x{d.height} @({d.x},{d.y})  "
              f"{d.orientation_label}{star}")
        print(f"      id={d.monitor_id}")
