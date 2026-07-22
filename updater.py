"""
Self-updater backed by GitHub Releases.

check_for_update()  -> queries the repo's latest release, compares its tag to
                       the local VERSION, and reports whether a newer one exists.
download_and_apply()-> downloads the release zip (a real .zip asset if present,
                       otherwise GitHub's source zipball), and overwrites the
                       app files in place. User data (profiles.json, logs) is
                       preserved.

Everything is best-effort and network-tolerant: any failure returns a clear
result/raises a friendly error rather than breaking the app.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import ssl
import sys
import urllib.request
import urllib.error
import webbrowser
import zipfile
from dataclasses import dataclass
from typing import Optional

import version as appversion

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
_RELEASES_PAGE = "https://github.com/{owner}/{repo}/releases/latest"
_UA = "monitor-kvm-updater"

# Files/dirs we never overwrite (user data + local state).
_PRESERVE = {"profiles.json", "settings.json", "switch.log", ".git"}


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@dataclass
class UpdateInfo:
    available: bool
    current: str
    latest: str = ""
    download_url: str = ""
    notes: str = ""
    html_url: str = ""
    error: str = ""


# ---------- version comparison ----------
def _parse(v: str) -> tuple:
    v = (v or "").strip().lstrip("vV")
    parts = []
    for tok in v.split("."):
        num = ""
        for ch in tok:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


# ---------- network ----------
def _http_get(url: str, accept: str = "application/vnd.github+json", timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def check_for_update(timeout: int = 8) -> UpdateInfo:
    cur = appversion.VERSION
    url = _API.format(owner=appversion.GITHUB_OWNER, repo=appversion.GITHUB_REPO)
    try:
        raw = _http_get(url, timeout=timeout)
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return UpdateInfo(available=False, current=cur, error="No releases published yet.")
        return UpdateInfo(available=False, current=cur, error=f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        return UpdateInfo(available=False, current=cur, error=str(e))

    tag = data.get("tag_name") or data.get("name") or ""
    html_url = data.get("html_url", "")
    notes = (data.get("body") or "").strip()

    # Prefer a .zip asset; fall back to the source zipball.
    dl = ""
    for asset in data.get("assets", []):
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip"):
            dl = asset.get("browser_download_url", "")
            break
    if not dl:
        dl = data.get("zipball_url", "")

    if tag and is_newer(tag, cur):
        return UpdateInfo(available=True, current=cur, latest=tag.lstrip("vV"),
                          download_url=dl, notes=notes, html_url=html_url)
    return UpdateInfo(available=False, current=cur, latest=tag.lstrip("vV"))


# ---------- apply ----------
def _detect_strip_prefix(names: list[str]) -> str:
    """GitHub zipballs wrap everything in a single top folder; strip it."""
    roots = {n.split("/")[0] for n in names if n and "/" in n}
    single = {n.split("/")[0] for n in names if n}
    if len(single) == 1:
        only = next(iter(single))
        # only strip if it truly is a wrapping folder (things live under it)
        if any(n.startswith(only + "/") for n in names):
            return only + "/"
    return ""


def _downloads_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def _apply_frozen(download_url: str) -> tuple[bool, str]:
    """When running as a packaged .exe we can't hot-swap the running binary
    safely, so download the release zip to the user's Downloads folder and open
    the releases page for a clean manual swap."""
    page = _RELEASES_PAGE.format(owner=appversion.GITHUB_OWNER, repo=appversion.GITHUB_REPO)
    saved = ""
    if download_url:
        try:
            blob = _http_get(download_url, accept="application/octet-stream", timeout=120)
            fname = download_url.split("/")[-1] or "monitor-kvm-update.zip"
            if not fname.lower().endswith(".zip"):
                fname += ".zip"
            saved = os.path.join(_downloads_dir(), fname)
            with open(saved, "wb") as fh:
                fh.write(blob)
        except Exception:  # noqa: BLE001
            saved = ""
    try:
        webbrowser.open(page)
    except Exception:  # noqa: BLE001
        pass
    if saved:
        return True, (f"Downloaded the new version to:\n{saved}\n"
                      "Close this app, unzip, and run the new .exe (opened the releases page too).")
    return True, ("Opened the releases page in your browser. Download the new .exe there, "
                  "then close and replace this one.")


def download_and_apply(download_url: str, project_dir: Optional[str] = None) -> tuple[bool, str]:
    if _is_frozen():
        return _apply_frozen(download_url)
    project_dir = project_dir or _HERE
    if not download_url:
        return False, "No download URL for the release."
    try:
        blob = _http_get(download_url, accept="application/octet-stream", timeout=60)
    except Exception as e:  # noqa: BLE001
        return False, f"Download failed: {e}"

    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return False, "Downloaded file was not a valid zip."

    names = zf.namelist()
    strip = _detect_strip_prefix(names)
    written = 0
    for n in names:
        if n.endswith("/"):
            continue
        rel = n[len(strip):] if strip and n.startswith(strip) else n
        if not rel:
            continue
        base = os.path.basename(rel)
        top = rel.split("/")[0]
        if rel in _PRESERVE or base in _PRESERVE or top in _PRESERVE:
            continue
        target = os.path.join(project_dir, *rel.split("/"))
        try:
            os.makedirs(os.path.dirname(target) or project_dir, exist_ok=True)
            with zf.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
        except PermissionError:
            # e.g. a file currently locked; skip but keep going
            continue
    if written == 0:
        return False, "Update package contained no applicable files."
    return True, f"Applied update: {written} file(s) updated. Restart to finish."


if __name__ == "__main__":
    info = check_for_update()
    print("current:", info.current, "| latest:", info.latest or "-",
          "| available:", info.available, "| note:", info.error or info.notes[:40])
