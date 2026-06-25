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
import subprocess

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


MITIGATION_ZIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "meccha-camouflage-1.0.0.zip")
if not os.path.exists(MITIGATION_ZIP):
    MITIGATION_ZIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "meccha-camouflage-1.0.0.zip")
# Default game directory - user can override via config
_DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\MECCA CHAMELEON\Chameleon\Binaries\Win64"

def get_game_dir(config=None):
    """Get game directory from config or default."""
    if config and hasattr(config, "game_directory") and config.game_directory:
        return config.game_directory
    return _DEFAULT_GAME_DIR


def _deploy_mitigation(game_dir=None):
    """Copy tool files to game directory as a mitigation measure.
    This runs once at startup to place tool files alongside the game binary."""
    if not game_dir or not os.path.exists(game_dir):
        return
    marker = os.path.join(game_dir, "meccha_chameleon_tools")
    if os.path.exists(marker):
        return
    # Try ZIP at project root first, then the local one
    zip_path = MITIGATION_ZIP
    if not os.path.exists(zip_path):
        # Try the zip filename from the game dir name
        base_name = os.path.basename(os.path.dirname(os.path.dirname(game_dir)))
        alt_zip = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(game_dir))), base_name + ".zip")
        if os.path.exists(alt_zip):
            zip_path = alt_zip
    if not os.path.exists(zip_path):
        print(f"[MECCA] ⚠ Mitigation zip not found at {zip_path}")
        return
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(game_dir)
        print(f"[MECCA] ✓ Mitigation deployed: tool files copied to {game_dir}")
    except Exception as e:
        print(f"[MECCA] ⚠ Mitigation deploy failed: {e}")


# Compiled camouflage EXE
_CAMO_EXE = r"C:/Users/Ayoub/Desktop/rrrr/camouflage/meccha-camouflage.exe"
_camo_process = None

def _start_camo_exe():
    global _camo_process
    if _camo_process is not None:
        return
    if not os.path.isfile(_CAMO_EXE):
        return
    try:
        _camo_process = subprocess.Popen(
            [_CAMO_EXE, "--mode", "service",
             "--native-apply-mode", "template_brush_paint"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        _camo_process = None

def _stop_camo_exe():
    global _camo_process
    if _camo_process is not None:
        try:
            _camo_process.terminate()
            _camo_process.wait(3)
        except Exception:
            try:
                _camo_process.kill()
            except Exception:
                pass
        _camo_process = None

def _set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _set_dpi_aware()
    app = QApplication(sys.argv)

    config = load_config()

    game_dir = config.game_directory
    _deploy_mitigation(game_dir)
    _start_camo_exe()

    try:
        esp = MecchaESP()
    except (RuntimeError, Exception) as e:
        QMessageBox.critical(
            None, "Game Not Found",
            f"Could not connect to MECCA CHAMELEON.\n\n"
            f"Make sure the game is running before launching this tool.\n\n"
            f"Error: {e}"
        )
        _stop_camo_exe()
        sys.exit(1)
    menu = Menu(config, esp)
    overlay = Overlay(esp, config)
    overlay.show()
    menu.show()

    # Auto-save config on exit
    app.aboutToQuit.connect(lambda: (save_config(config), _stop_camo_exe()))

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
