#!/usr/bin/env python3
"""Update checker/downloader for Meccha Chameleon Tools.

Queries the GitHub Releases API to detect newer versions and downloads the
packaged .exe asset directly from the UI.
"""
import json
import os
import re
import sys
import ssl
import urllib.request
from typing import Callable, Optional

try:
    import certifi
    _CA_BUNDLE = certifi.where()
except ImportError:
    _CA_BUNDLE = None

APP_VERSION = "1.9.2.1-beta"
GITHUB_REPO = "SilentJMA/Meccha-Chameleon-Tools"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

# When True, pre-releases (beta/rc) are considered when checking for updates.
INCLUDE_PRERELEASES = True

_USER_AGENT = "MecchaChameleonTools-Updater"


def _parse_version(text):
    """Parse a version string like 'v1.9.2-beta' into a comparable tuple.

    Returns (major, minor, patch, pre) where pre is 0 for pre-releases and
    1 for stable (so stable sorts after its own pre-release).
    """
    if not text:
        return (0, 0, 0, 0)
    text = text.strip().lstrip("vV")
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)", text)
    if not m:
        return (0, 0, 0, 0)
    major = int(m.group(1) or 0)
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    suffix = (m.group(4) or "").strip(" -_.").lower()
    pre = 0 if suffix else 1
    return (major, minor, patch, pre)


def is_newer(remote_version, current_version=APP_VERSION):
    return _parse_version(remote_version) > _parse_version(current_version)


def _open_url(url, timeout=10):
    kwargs = {}
    if _CA_BUNDLE:
        kwargs["cafile"] = _CA_BUNDLE
    ctx = ssl.create_default_context(**kwargs)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _release_to_info(data):
    tag = data.get("tag_name") or data.get("name") or ""
    asset_url = None
    asset_name = None
    asset_size = 0
    for asset in data.get("assets", []) or []:
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            asset_url = asset.get("browser_download_url")
            asset_name = name
            asset_size = asset.get("size", 0)
            break
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "notes": data.get("body", "") or "",
        "page_url": data.get("html_url") or RELEASES_PAGE,
        "asset_url": asset_url,
        "asset_name": asset_name,
        "asset_size": asset_size,
    }


def check_for_update(current_version=APP_VERSION, timeout=10,
                     include_prereleases=INCLUDE_PRERELEASES) -> Optional[dict]:
    """Return update info dict for the newest release, or None if up to date.

    Fetches the releases list so pre-releases (betas) are detected. Only
    releases that ship a downloadable .exe asset are considered. Raises on
    network/parse errors so the caller can surface a message.
    """
    with _open_url(RELEASES_API, timeout=timeout) as resp:
        releases = json.loads(resp.read().decode("utf-8"))

    best = None
    best_ver = _parse_version(current_version)
    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prereleases:
            continue
        tag = rel.get("tag_name") or rel.get("name") or ""
        ver = _parse_version(tag)
        if ver > best_ver:
            # Prefer releases that actually have an .exe asset.
            has_exe = any(
                (a.get("name", "").lower().endswith(".exe"))
                for a in (rel.get("assets", []) or [])
            )
            if has_exe:
                best = rel
                best_ver = ver

    if best is None:
        return None
    return _release_to_info(best)


def default_download_dir() -> str:
    """Directory next to the running executable (or cwd when run from source)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


def download_update(asset_url, dest_path,
                    progress_cb: Optional[Callable[[int, int], None]] = None,
                    timeout=30) -> str:
    """Download asset_url to dest_path, reporting (downloaded, total) bytes.

    Writes to a temporary '.part' file then atomically renames on success.
    Returns the final path.
    """
    tmp_path = dest_path + ".part"
    with _open_url(asset_url, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        with open(tmp_path, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)
    os.replace(tmp_path, dest_path)
    return dest_path
