#!/usr/bin/env python3
"""
MECCHA CHAMELEON Box ESP — Entry Point
Fully external box ESP for MECCHA CHAMELEON (Steam / UE5.6).
"""
import sys
import os
import zipfile
import shutil
import ctypes
import json
import urllib.request
import urllib.error

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer

# Re-export for backward compatibility with debug scripts
from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, ru16, rfloat, wfloat, rvec3, rvec3_f,
    read_array, read_tarray_ptr, dist, OFFSETS,
    PatternScanner, FNameResolver, UObjectArray, OffsetResolver,
)
from meccha_chameleon_tools.config import Config, load_config, save_config, CONFIG_FILE
from meccha_chameleon_tools.ui import Menu, Overlay


MITIGATION_ZIP = r"C:\Users\Ayoub\Downloads\meccha-camouflage-1.0.0.zip"
GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\MECCHA CHAMELEON\Chameleon\Binaries\Win64"


def _deploy_mitigation():
    """Copy tool files to game directory as a mitigation measure.
    This runs once at startup to place tool files alongside the game binary."""
    if not os.path.exists(GAME_DIR):
        return
    marker = os.path.join(GAME_DIR, "meccha_chameleon_tools")
    if os.path.exists(marker):
        return
    if not os.path.exists(MITIGATION_ZIP):
        print(f"[MECCA] ⚠ Mitigation zip not found at {MITIGATION_ZIP}")
        return
    try:
        with zipfile.ZipFile(MITIGATION_ZIP) as zf:
            zf.extractall(GAME_DIR)
        print(f"[MECCA] ✓ Mitigation deployed: tool files copied to game directory")
    except Exception as e:
        print(f"[MECCA] ⚠ Mitigation deploy failed: {e}")


def _set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _prompt_camouflage(config):
    """Ask the user whether to enable camouflage (optional DEV feature).
    Camouflage is disabled by default — user must opt in at each startup.
    Returns the (possibly modified) config."""
    msg = QMessageBox()
    msg.setWindowTitle("MECCHA CHAMELEON TOOLS")
    msg.setText("Camouflage Feature (DEV — Experimental)")
    msg.setInformativeText(
        "The camouflage feature samples screen colors (F10 key) and applies them "
        "to your character's 3D model in-game.\n\n"
        "\u26a0 This feature is in DEVELOPMENT \u2014 it may be unstable or have no "
        "visible effect depending on the game version.\n\n"
        "Would you like to enable it?"
    )
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.setIcon(QMessageBox.Question)
    if msg.exec_() == QMessageBox.Yes:
        config.camouflage_enabled = True
        print("[CAMO] Camouflage enabled by user (DEV mode)")
    else:
        config.camouflage_enabled = False
        print("[CAMO] Camouflage remains disabled (default)")
    return config


def _fetch_and_install_release(target_dir):
    """Download the latest MecchaCamouflage release from GitHub and install it."""
    api_url = "https://api.github.com/repos/acentrist/MecchaCamouflage/releases/latest"
    print("[CAMO] Fetching latest release info from GitHub...")
    try:
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "MecchaCamouflage/1.0",
            "Accept": "application/vnd.github.v3+json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "latest")
        assets = data.get("assets", [])
        if not assets:
            print(f"[CAMO] \u26a0 No downloadable assets found in release {tag}")
            QMessageBox.information(
                None, "No Assets",
                f"Release {tag} has no downloadable assets (exe/zip)."
            )
            return

        # Prefer .exe, fallback to .zip, then first available
        asset = None
        for a in assets:
            if a["name"].lower().endswith(".exe"):
                asset = a
                break
        if not asset:
            for a in assets:
                if a["name"].lower().endswith(".zip"):
                    asset = a
                    break
        if not asset:
            asset = assets[0]

        download_url = asset["browser_download_url"]
        filename = asset["name"]
        size_mb = asset.get("size", 0) / (1024 * 1024)
        dest = os.path.join(target_dir, filename)

        print(f"[CAMO] Downloading {filename} ({size_mb:.1f} MB) ...")
        urllib.request.urlretrieve(download_url, dest)
        print(f"[CAMO] \u2713 Saved to {dest}")

        # Extract if a zip archive
        if filename.lower().endswith(".zip"):
            print(f"[CAMO] Extracting {filename} ...")
            with zipfile.ZipFile(dest) as zf:
                zf.extractall(target_dir)
            os.remove(dest)
            print(f"[CAMO] \u2713 Extracted to {target_dir}")

        QMessageBox.information(
            None, "Install Complete",
            f"\u2713 Latest release {tag} downloaded and installed to:\n{target_dir}"
        )

    except urllib.error.HTTPError as e:
        print(f"[CAMO] \u26a0 HTTP error: {e.code} {e.reason}")
        QMessageBox.warning(
            None, "Download Failed",
            f"Could not fetch the latest release.\nHTTP {e.code}: {e.reason}"
        )
    except Exception as e:
        print(f"[CAMO] \u26a0 Download failed: {e}")
        QMessageBox.warning(
            None, "Download Failed",
            f"An error occurred while downloading the latest release:\n{e}"
        )


def _prompt_install_release():
    """Ask the user whether to download & install the latest release to the game dir."""
    if not os.path.exists(GAME_DIR):
        print(f"[CAMO] Game directory not found, skipping install prompt: {GAME_DIR}")
        return

    msg = QMessageBox()
    msg.setWindowTitle("MECCHA CHAMELEON TOOLS")
    msg.setText("Install Latest Release?")
    msg.setInformativeText(
        f"Do you want to download the latest MecchaCamouflage release from GitHub "
        f"and install it to:\n\n{GAME_DIR}\n\n"
        f"This will download the newest version of the tool directly into your game directory."
    )
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.Yes)
    msg.setIcon(QMessageBox.Question)
    if msg.exec_() == QMessageBox.Yes:
        _fetch_and_install_release(GAME_DIR)


def main():
    _set_dpi_aware()
    _deploy_mitigation()
    app = QApplication(sys.argv)

    config = load_config()

    # ── Startup prompts ────────────────────────────────────────────────
    # 1. Ask about camouflage (optional, DEV — disabled by default)
    config = _prompt_camouflage(config)
    # 2. Ask about downloading the latest release to the game directory
    _prompt_install_release()
    # ───────────────────────────────────────────────────────────────────

    try:
        esp = MecchaESP()
    except (RuntimeError, Exception) as e:
        QMessageBox.critical(
            None, "Game Not Found",
            f"Could not connect to MECCHA CHAMELEON.\n\n"
            f"Make sure the game is running before launching this tool.\n\n"
            f"Error: {e}"
        )
        sys.exit(1)
    menu = Menu(config, esp)
    overlay = Overlay(esp, config)
    overlay.show()
    menu.show()

    # Auto-save config on exit
    app.aboutToQuit.connect(lambda: save_config(config))

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
