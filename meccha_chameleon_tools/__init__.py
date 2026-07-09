#!/usr/bin/env python3
"""
MECCHA CHAMELEON Box ESP — Entry Point
Fully external box ESP for MECCHA CHAMELEON (Steam / UE5.6).
"""
import sys
import os
import ctypes

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer

# Re-export for backward compatibility with debug scripts
from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, ru16, rfloat, wfloat, rvec3, rvec3_f,
    read_array, read_tarray_ptr, dist, OFFSETS,
    PatternScanner, FNameResolver, UObjectArray, OffsetResolver,
)
from meccha_chameleon_tools.config import Config, load_config, save_config, CONFIG_FILE
from meccha_chameleon_tools.translations import _tr
from meccha_chameleon_tools.ui import Menu, Overlay
from meccha_chameleon_tools.updater import APP_VERSION as __version__


# Default game directory - user can override via config
_DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\MECCA CHAMELEON\Chameleon\Binaries\Win64"

def get_game_dir(config=None):
    """Get game directory from config or default."""
    if config and hasattr(config, "game_directory") and config.game_directory:
        return config.game_directory
    return _DEFAULT_GAME_DIR


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
    _tr.set_language(config.language)

    try:
        esp = MecchaESP()
    except (RuntimeError, Exception) as e:
        QMessageBox.critical(
            None, "Game Not Found",
            f"Could not connect to MECCA CHAMELEON.\n\n"
            f"Make sure the game is running before launching this tool.\n\n"
            f"Error: {e}"
        )
        sys.exit(1)
    menu = Menu(config, esp)
    overlay = Overlay(esp, config)
    overlay.show()
    menu.show()

    # Auto-save config + cleanup on exit
    app.aboutToQuit.connect(lambda: (save_config(config), esp.cleanup()))

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
