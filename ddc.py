"""
DDC/CI backend built on NirSoft ControlMyMonitor.exe.

Why ControlMyMonitor instead of pure-Python DDC?
  On Windows the physical-monitor DDC/CI path is flaky through many Python
  libs (monitorcontrol frequently reports "The request is not supported" or
  only enumerates a single logical monitor). ControlMyMonitor talks to the
  physical monitor handles reliably and exposes a clean command line, so we
  shell out to it.

Monitor identity:
  We identify monitors by their SERIAL NUMBER when available (stable across
  cable/port changes -- essential for a KVM), falling back to the short
  monitor id, then the display name, then the enumeration index.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from apppaths import resource_dir
from vcp_inputs import INPUT_SOURCE_VCP

_HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL_MY_MONITOR = os.path.join(resource_dir(), "tools", "ControlMyMonitor.exe")

# ControlMyMonitor returns 0xFFFFFFFF (as signed -1 or unsigned 4294967295)
# from /GetValue when it cannot read the feature.
_GET_ERROR_VALUES = {0xFFFFFFFF, -1}


@dataclass
class Monitor:
    index: int
    device_name: str = ""    # e.g. \\.\DISPLAY3\Monitor0 (unique this session)
    name: str = ""
    serial: str = ""
    short_id: str = ""
    monitor_id: str = ""     # MONITOR\... (matches Windows display device id)
    adapter: str = ""

    @property
    def stable_id(self) -> str:
        """The identifier we pass to ControlMyMonitor for get/set.

        Prefer identifiers that survive a cable/port change (serial, short id)
        so a KVM profile keeps matching the same physical panel. Fall back to
        the per-session device name, then the enumeration index.
        """
        if self.serial and self.serial.strip():
            return self.serial.strip()
        if self.short_id and self.short_id.strip():
            return self.short_id.strip()
        if self.device_name and self.device_name.strip():
            return self.device_name.strip()
        if self.name and self.name.strip():
            return self.name.strip()
        return str(self.index)

    @property
    def display_label(self) -> str:
        bits = [self.name or self.short_id or f"Monitor {self.index}"]
        if self.serial:
            bits.append(f"S/N {self.serial}")
        elif self.short_id:
            bits.append(self.short_id)
        return "  \u2013  ".join(bits)


class DDCError(RuntimeError):
    pass


def _ensure_tool() -> None:
    if not os.path.exists(CONTROL_MY_MONITOR):
        raise DDCError(
            f"ControlMyMonitor.exe not found at {CONTROL_MY_MONITOR}. "
            "Re-run setup to download it."
        )


def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    _ensure_tool()
    return subprocess.run(
        [CONTROL_MY_MONITOR, *args],
        capture_output=capture,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _read_text_any_encoding(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            # crude sanity check: decoded text should contain a known field label
            if "Monitor" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _parse_field(line: str) -> tuple[str, str] | None:
    """Parse a `Field: "Value"` line -> (key_lower, value)."""
    if ":" not in line:
        return None
    key, _, val = line.partition(":")
    key = key.strip().lower()
    val = val.strip()
    if val.startswith('"') and val.endswith('"') and len(val) >= 2:
        val = val[1:-1]
    return key, val


def list_monitors() -> list[Monitor]:
    """Enumerate physically-attached monitors via /smonitors.

    /smonitors writes a simple text file: repeated blocks of `Field: "Value"`
    lines separated by blank lines. Fields include Monitor Device Name,
    Monitor Name, Serial Number, Adapter Name, Monitor ID, Short Monitor ID.
    """
    _ensure_tool()
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="cmm_")
    os.close(fd)
    try:
        _run(["/smonitors", path], capture=True)
        text = _read_text_any_encoding(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not text.strip():
        return []

    # Split into per-monitor blocks. A new block starts at "Monitor Device Name".
    monitors: list[Monitor] = []
    current: dict[str, str] = {}

    def flush():
        if current:
            monitors.append(
                Monitor(
                    index=len(monitors),
                    device_name=current.get("monitor device name", ""),
                    name=current.get("monitor name", ""),
                    serial=current.get("serial number", ""),
                    short_id=current.get("short monitor id", ""),
                    monitor_id=current.get("monitor id", ""),
                    adapter=current.get("adapter name", ""),
                )
            )

    for line in text.splitlines():
        parsed = _parse_field(line)
        if not parsed:
            continue
        key, val = parsed
        if key == "monitor device name" and current:
            flush()
            current = {}
        current[key] = val
    flush()
    return monitors


def get_input_source(monitor: Monitor) -> Optional[int]:
    """Read current VCP 0x60 value. Returns None if unreadable."""
    cp = _run(["/GetValue", monitor.stable_id, f"{INPUT_SOURCE_VCP:02X}"])
    # ControlMyMonitor puts the value in the process exit code.
    code = cp.returncode
    if code in _GET_ERROR_VALUES:
        return None
    if code < 0:
        code &= 0xFFFFFFFF
        if code in _GET_ERROR_VALUES:
            return None
    return code & 0xFF


def set_input_source(monitor: Monitor, value: int) -> None:
    """Write VCP 0x60 to switch the monitor's active input."""
    _run(["/SetValue", monitor.stable_id, f"{INPUT_SOURCE_VCP:02X}", str(int(value))])


def self_test() -> str:
    """Human-readable snapshot of what the backend currently sees."""
    lines = []
    try:
        mons = list_monitors()
    except DDCError as e:
        return f"Backend error: {e}"
    if not mons:
        return "No monitors detected via DDC/CI (are any connected & DDC/CI enabled?)."
    for m in mons:
        cur = get_input_source(m)
        cur_txt = f"0x{cur:02X}" if cur is not None else "unreadable"
        lines.append(f"[{m.index}] {m.display_label}  ->  current input {cur_txt}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(self_test())
